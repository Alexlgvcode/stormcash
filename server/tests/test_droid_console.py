"""GET /v1/droid/console: Droid's stored runs, outcomes, totals and guardrails (spec §18.7)."""

from __future__ import annotations

import datetime as dt

from psycopg.types.json import Jsonb

from stormcash.routes import droid_console as dc

NOW = dt.datetime(2026, 10, 17, 20, 0, tzinfo=dt.timezone.utc)
USAGE = {"input_tokens": 440, "output_tokens": 3587, "factory_credits": 70319.0}
FLAG = {"kind": "merchant_silence", "proposed_action": "hold_pool_payout", "severity": "review"}


def row(run_id: int, runner: str = "droid", status: str = "succeeded", job: str = "triage", seconds: float = 45,
        steps=(("ToolSearch", True), ("get_candidate", True), ("get_merchant_payments", True)), error=None,
        output=FLAG, **meta) -> dict:
    """A stormdesk_runs row as RUNS_SQL returns it."""
    started = NOW - dt.timedelta(seconds=seconds + 60)
    transcript = {"runner": runner, "missing_citations": [], "error": error, "fallback_from_droid": None,
                  "model": "claude-sonnet-5-5" if runner == "droid" else None,
                  "model_requested": "claude-sonnet-5-5" if runner == "droid" else None,
                  "usage": USAGE if runner == "droid" else None, "fallback_usage": None,
                  "prompt_version": 2 if runner == "droid" else None, **meta}
    return {"run_id": run_id, "job": job, "case_id": 11 if job == "investigate" else None,
            "candidate_id": 16 if job in ("triage", "review") else None, "merchant_id": None, "runner": runner, "status": status,
            "citations_valid": status == "succeeded", "session_id": f"{runner}-{run_id}", "error": error,
            "output": output, "started_at": started,
            "finished_at": None if status == "running" else started + dt.timedelta(seconds=seconds),
            "duration_ms": None if status == "running" else int(seconds * 1000), "meta": transcript,
            "steps": [list(s) for s in steps], "case_rule": "SAME_COUNTER" if job == "investigate" else None,
            "candidate_kind": "merchant_silence" if job in ("triage", "review") else None, "subject_name": "Corner Store"}


FIXTURE = [
    row(1),  # valid, Droid
    row(2, status="invalid", missing_citations=["63da8c17"], output={**FLAG, "kind": "none"}),
    row(3, status="failed", error="error_structured_output: no output", output=None, seconds=90),
    row(4, runner="fake", seconds=1, fallback_from_droid="error_during_execution: model_usage_exhausted",
        fallback_usage={"factory_credits": 12.0}),
    row(5, runner="fake", seconds=1),  # STORMDESK_RUNNER=fake
    row(6, status="failed", error="TimeoutError: ", output=None),
    row(7, attempts=[{"attempt": 1, "ok": False, "error": "error_structured_output"}, {"attempt": 2, "ok": True}],
        permission_denials=[{"tool": "Execute", "server": None}]),
    row(8, job="investigate", output={"verified_independently": True}, attempts=[{"attempt": 1, "ok": True}],
        permission_denials=[]),
    row(9, status="running", output=None, seconds=0),
    row(10, status="running", output=None, seconds=3600),  # started an hour ago, never finished
]


def console(rows=FIXTURE, limit=200) -> dict:
    return dc.console(rows, NOW.timestamp(), limit)


def test_each_run_gets_its_outcome():
    runs = {r["run_id"]: r for r in console()["runs"]}
    assert [runs[i]["outcome"] for i in range(1, 11)] == [
        "valid", "invalid_citation", "structured_output_failed", "fallback", "fake", "failed", "valid", "valid",
        "running", "unfinished"]
    one = runs[1]
    assert (one["model"], one["model_requested"], one["prompt_version"]) == ("claude-sonnet-5-5", "claude-sonnet-5-5", 2)
    assert (one["duration_ms"], one["factory_credits"]) == (45_000, 70319.0)
    # Our read-only tools are counted; Droid's ToolSearch is reported apart, not hidden.
    assert one["tool_calls"] == 2 and one["other_calls"] == {"ToolSearch": 1}
    assert one["subject"] == "candidate #16 · merchant_silence · Corner Store"
    assert one["verdict"] == "merchant_silence → hold_pool_payout" and runs[2]["verdict"] == "dismissed"
    assert runs[8]["subject"] == "case #11 · SAME_COUNTER" and runs[8]["verdict"] == "rule re-verified"
    # A fallback shows what Droid's failed attempt cost; a plain fake run cost no credits.
    assert runs[4]["factory_credits"] == 12.0 and runs[5]["factory_credits"] is None
    assert runs[4]["fallback_reason"].endswith("model_usage_exhausted")


def test_retries_and_denials_are_unknown_unless_recorded():
    runs = {r["run_id"]: r for r in console()["runs"]}
    assert runs[1]["structured_output_retries"] is None and runs[1]["permission_denials"] is None
    assert runs[3]["structured_output_retries"] == 1  # a failed structured output is stored only after its retry
    assert runs[7]["structured_output_retries"] == 1 and runs[7]["permission_denials"] == 1
    assert runs[8]["structured_output_retries"] == 0 and runs[8]["permission_denials"] == 0
    assert runs[5]["structured_output_retries"] is None  # the fake runner has no structured output to retry


def test_totals_count_only_droid_and_keep_fake_runs_apart():
    out = console()
    t = out["totals"]
    # Droid's finished runs: 1, 2, 3, 6, 7, 8 (running and never-finished ones aren't scored).
    assert (t["droid_runs"], t["valid"]) == (6, 3) and t["success_rate"] == 0.5
    assert (t["fake_runs"], t["fallback_runs"], t["running"], t["unfinished"]) == (1, 1, 1, 1)
    assert t["credits_runs"] == 6 and t["credits_total"] == 6 * 70319.0 and t["mean_credits"] == 70319.0
    assert t["mean_duration_ms"] == (45_000 * 5 + 90_000) / 6
    assert t["outcomes"] == {"valid": 3, "invalid_citation": 1, "structured_output_failed": 1, "failed": 1}
    by_job = {j["job"]: j for j in out["by_job"]}
    assert list(by_job) == ["investigate", "triage", "respond"]
    assert (by_job["investigate"]["droid_runs"], by_job["investigate"]["success_rate"]) == (1, 1.0)
    assert (by_job["triage"]["droid_runs"], by_job["triage"]["valid"]) == (5, 2)
    assert by_job["respond"]["droid_runs"] == 0 and by_job["respond"]["success_rate"] is None
    assert out["builtin_calls_seen"] == {"ToolSearch": 8}


def test_only_fake_runs_give_no_success_rate():
    t = console([row(1, runner="fake"), row(2, runner="fake")])["totals"]
    assert t["droid_runs"] == 0 and t["success_rate"] is None and t["mean_credits"] is None and t["fake_runs"] == 2


def test_guardrails_list_the_runs_where_they_fired():
    g = {x["key"]: x for x in console()["guardrails"]}
    assert g["invalid_citation"]["count"] == 1 and g["invalid_citation"]["events"][0]["run_id"] == 2
    assert g["structured_output_failed"]["count"] == 1 and g["structured_output_failed"]["events"][0]["run_id"] == 3
    assert g["fallback"]["count"] == 1 and g["fallback"]["events"][0]["run_id"] == 4
    # Only runs 7 and 8 record retries and denials: the counts say so.
    assert (g["structured_output_retry"]["count"], g["structured_output_retry"]["recorded_runs"]) == (1, 2)
    assert g["structured_output_retry"]["events"][0]["run_id"] == 7
    assert (g["permission_denial"]["count"], g["permission_denial"]["recorded_runs"]) == (1, 2)


def test_unrecorded_guardrails_are_null_never_zero():
    old = [row(1), row(2, status="invalid", missing_citations=["x"])]
    g = {x["key"]: x for x in console(old)["guardrails"]}
    assert g["structured_output_retry"]["count"] is None and g["structured_output_retry"]["recorded_runs"] == 0
    assert g["permission_denial"]["count"] is None and g["permission_denial"]["recorded_runs"] == 0
    assert g["invalid_citation"]["count"] == 1 and g["fallback"]["count"] == 0  # these are always recorded


def test_reviews_get_their_own_totals_and_verdicts():
    """The second-opinion Droid (§14.7b): job 'review', output.verdict, transcript.reviewed.run_id."""
    def review(run_id, verdict, **kw):
        out = {"verdict": verdict, "reasons": ["…"], "evidence_ids": []}
        return row(run_id, job="review", output=out, reviewed={"flag_id": 16, "run_id": 1, "proposal": FLAG}, **kw)

    reviews = [review(11, "disagree"), review(12, "agree"), review(13, "agree", runner="fake"),
               review(14, "agree", status="invalid")]
    out = console([*FIXTURE, *reviews])
    assert [j["job"] for j in out["by_job"]] == ["investigate", "triage", "respond", "review"]
    by_job = {j["job"]: j for j in out["by_job"]}
    assert (by_job["review"]["droid_runs"], by_job["review"]["valid"], by_job["review"]["fake_runs"]) == (3, 2, 1)
    runs = {r["run_id"]: r for r in out["runs"]}
    assert runs[11]["verdict"] == "disagrees" and runs[11]["reviewed_run_id"] == 1
    assert runs[11]["subject"] == "candidate #16 · merchant_silence · Corner Store"  # reviews keep their candidate
    # Only valid Droid reviews count as verdicts: not the fake reviewer's, not an invalid one.
    assert out["review_verdicts"] == {"agree": 1, "disagree": 1}
    assert console()["review_verdicts"] == {}


def test_limit_trims_the_list_not_the_totals():
    out = console(limit=3)
    assert len(out["runs"]) == 3 and out["run_count"] == 10 and out["totals"]["droid_runs"] == 6


def test_no_runs_yet(app_client):
    out = app_client.get("/v1/droid/console").json()
    assert out["run_count"] == 0 and out["runs"] == [] and out["totals"]["success_rate"] is None
    assert out["harness"]["read_only_tools"][0] == "get_case" and len(out["harness"]["read_only_tools"]) == 11
    assert out["harness"]["builtin_tools_disabled"] == 34 and out["harness"]["mcp_server"] == "stormdesk"


def test_endpoint_reads_stored_runs(app_client, deps):
    """Real rows through RUNS_SQL: a Droid run, an invalid one and a fallback, newest first."""
    with deps.pool.connection() as conn:
        for r in (row(1), row(2, status="invalid", missing_citations=["63da8c17"]),
                  row(3, runner="fake", fallback_from_droid="error_during_execution: model_usage_exhausted")):
            meta = {**r["meta"], "steps": [{"index": i, "tool": t, "ok": ok, "input_summary": "{}"}
                                           for i, (t, ok) in enumerate(r["steps"])]}
            conn.execute(
                """INSERT INTO stormdesk_runs (job, runner, status, output, citations_valid, transcript, session_id,
                                               error, started_at, finished_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (r["job"], r["runner"], r["status"], Jsonb(r["output"]), r["citations_valid"], Jsonb(meta),
                 r["session_id"], r["error"], r["started_at"], r["finished_at"]))
        conn.execute("INSERT INTO stormdesk_runs (job, runner, status) VALUES ('investigate', 'pending', 'running')")
    out = app_client.get("/v1/droid/console").json()
    assert [r["run_id"] for r in out["runs"]] == [4, 3, 2, 1]
    assert [r["outcome"] for r in out["runs"]] == ["running", "fallback", "invalid_citation", "valid"]
    first = out["runs"][-1]
    assert first["duration_ms"] == 45_000 and first["tool_calls"] == 2 and first["other_calls"] == {"ToolSearch": 1}
    assert isinstance(first["started_at"], int) and first["subject"] == "—"
    assert (out["totals"]["droid_runs"], out["totals"]["valid"], out["totals"]["fallback_runs"]) == (2, 1, 1)
    g = {x["key"]: x for x in out["guardrails"]}
    assert g["invalid_citation"]["count"] == 1 and g["permission_denial"]["count"] is None
