"""The reviewer Droid (spec §14.7b): a second session tries to refute each triage Flag before a person sees it.
Agreement passes the flag through; a valid disagreement marks it "agents disagree" and keeps it open for a
person; the reviewer never acts."""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from stormcash.db import all_rows, one, scalar
from stormcash.stormdesk import runner
from stormcash.stormdesk.prompt import REVIEW_PROMPT_VERSION
from stormcash.stormdesk.runner import Job, RunOutcome, Steps
from stormcash.stormdesk.schemas import Review
from stormcash.stormdesk.service import StormDesk, after_review, review_job

from .test_stormdesk import OPERATOR, double_spend, flag, patch_droid, run, world  # noqa: F401  (fixtures)


class Scripted:
    """A stand-in agent with a fixed answer; `name` is the runner it claims to be."""

    def __init__(self, output, name: str = "droid"):
        self.output, self.name = output, name

    async def run(self, job: Job, prompt: str, steps: Steps) -> RunOutcome:
        self.prompt = prompt
        step = steps.call("get_candidate", {"candidate_id": job.candidate_id})
        steps.result(None, True, step)
        return RunOutcome(self.name, self.output, f"{self.name}-1")


def cheat_id(double_spend) -> str:
    return double_spend["cheat"].tag.tag_hash.hex()


def subject(deps, double_spend) -> str:
    with deps.pool.connection() as conn:
        return scalar(conn, "SELECT subject_id FROM candidates WHERE candidate_id = %s", (double_spend["candidate_id"],))


def triage(desk: StormDesk, double_spend, output=None) -> dict:
    """A stored triage flag: the fake runner's baseline, or a scripted Droid proposal."""
    job = Job("triage", candidate_id=double_spend["candidate_id"])
    return run(desk, job, Scripted(output) if output is not None else None)


def review(desk: StormDesk, flag_id: int, output=None) -> dict:
    return asyncio.run(desk.review(flag_id=flag_id, runner=Scripted(output) if output is not None else None))


def stored_flag(deps) -> dict:
    with deps.pool.connection() as conn:
        return one(conn, "SELECT * FROM flags")


def test_the_fake_reviewer_agrees_with_the_baseline_and_is_labelled(deps, double_spend):
    desk = StormDesk(deps)
    flag_id = triage(desk, double_spend)["flag"]["flag_id"]
    out = review(desk, flag_id)
    assert (out["job"], out["runner"], out["status"], out["citations_valid"]) == ("review", "fake", "succeeded", True)
    assert out["output"]["verdict"] == "agree" and out["session_id"].startswith("fake-")
    assert all(r.startswith("Fake reviewer:") for r in out["output"]["reasons"])
    assert out["output"]["evidence_ids"] == [cheat_id(double_spend)]  # re-read in the shop's payments itself
    assert out["prompt_version"] is None  # no Droid prompt answered it
    assert out["after_review"] == {"status": "open", "agents_disagree": False, "kind": "merchant_silence",
                                   "proposed_action": "hold_pool_payout"}
    f = stored_flag(deps)
    assert (f["status"], f["agents_disagree"]) == ("open", False)
    assert f["review"]["verdict"] == "agree" and f["review"]["runner"] == "fake" and f["review"]["run_id"] == out["run_id"]
    with deps.pool.connection() as conn:
        runs = all_rows(conn, "SELECT job, candidate_id, transcript FROM stormdesk_runs ORDER BY run_id")
    assert [r["job"] for r in runs] == ["triage", "review"] and runs[1]["candidate_id"] == double_spend["candidate_id"]
    assert [s["tool"] for s in runs[1]["transcript"]["steps"]] == ["get_candidate", "get_merchant_payments"]
    assert runs[1]["transcript"]["reviewed"]["run_id"] == f["agent_transcript"]["run_id"]


def test_a_disagreement_keeps_the_flag_open_for_a_person(deps, double_spend, app_client):
    desk = StormDesk(deps)
    dismissal = flag(kind="none", severity="info", proposed_action="none", subject_id=subject(deps, double_spend))
    flag_id = triage(desk, double_spend, dismissal)["flag"]["flag_id"]
    assert stored_flag(deps)["status"] == "dismissed"
    out = review(desk, flag_id, Review(verdict="disagree", reasons=["The shop took pool money from a cheater."],
                                       evidence_ids=[cheat_id(double_spend)], suggested_kind="merchant_silence",
                                       suggested_severity="urgent", suggested_action="hold_pool_payout"))
    assert out["after_review"]["status"] == "open" and out["after_review"]["agents_disagree"]
    f = stored_flag(deps)
    assert (f["status"], f["agents_disagree"]) == ("open", True)
    # Both views stay: StormDesk's proposal is untouched, the reviewer's is next to it.
    assert (f["kind"], f["proposed_action"]) == ("none", "none")
    assert f["review"]["suggested_action"] == "hold_pool_payout" and f["review"]["reasons"]
    # A person decides, with the same deterministic Approve as any open flag: StormDesk's proposal, nothing else.
    decided = app_client.post(f"/v1/flags/{flag_id}/approve", json={"note": "seen both"}, headers=OPERATOR).json()
    assert (decided["status"], decided["executed_actions"]) == ("approved", {"action": "none"})
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT pool_eligible FROM merchants WHERE merchant_id = %s",
                      (bytes.fromhex(subject(deps, double_spend)),)) is True  # nothing held: the reviewer never acts


def test_insufficient_evidence_escalates_an_open_flag_too(deps, double_spend):
    desk = StormDesk(deps)
    flag_id = triage(desk, double_spend)["flag"]["flag_id"]
    review(desk, flag_id, Review(verdict="insufficient_evidence", reasons=["One payment proves nothing."],
                                 evidence_ids=[]))
    f = stored_flag(deps)
    assert (f["status"], f["agents_disagree"], f["proposed_action"]) == ("open", True, "hold_pool_payout")


def test_agreement_leaves_a_dismissal_dismissed(deps, double_spend):
    desk = StormDesk(deps)
    dismissal = flag(kind="none", severity="info", proposed_action="none", subject_id=subject(deps, double_spend))
    flag_id = triage(desk, double_spend, dismissal)["flag"]["flag_id"]
    review(desk, flag_id, Review(verdict="agree", reasons=["Honest shop."], evidence_ids=[cheat_id(double_spend)]))
    assert (stored_flag(deps)["status"], stored_flag(deps)["agents_disagree"]) == ("dismissed", False)


def test_a_review_with_an_invented_id_doesnt_count(deps, double_spend):
    desk = StormDesk(deps)
    flag_id = triage(desk, double_spend)["flag"]["flag_id"]
    out = review(desk, flag_id, Review(verdict="disagree", reasons=["r"], evidence_ids=["cd" * 32]))
    assert (out["status"], out["missing_citations"]) == ("invalid", ["cd" * 32])
    f = stored_flag(deps)
    assert (f["status"], f["agents_disagree"], f["review"]["status"]) == ("open", False, "invalid")


def test_the_fake_reviewers_rules_comparison_never_escalates(deps, double_spend):
    desk = StormDesk(deps)
    dismissal = flag(kind="none", severity="info", proposed_action="none", subject_id=subject(deps, double_spend))
    flag_id = triage(desk, double_spend, dismissal)["flag"]["flag_id"]
    out = review(desk, flag_id)  # the fake runner: the baseline would flag it
    assert out["runner"] == "fake" and out["output"]["verdict"] == "disagree"
    assert out["output"]["suggested_action"] == "hold_pool_payout" and "a person decides" in out["output"]["reasons"][-1]
    f = stored_flag(deps)
    assert (f["status"], f["agents_disagree"]) == ("dismissed", False)  # rules only isn't a second opinion


def test_a_review_doesnt_count_once_decided_or_re_triaged(deps, double_spend, app_client):
    desk = StormDesk(deps)
    flag_id = triage(desk, double_spend)["flag"]["flag_id"]
    no = Review(verdict="disagree", reasons=["r"], evidence_ids=[])
    # Re-triaged while the review ran: the review is of an older proposal, so the flag keeps its new one.
    job = review_job(deps, flag_id)
    triage(desk, double_spend)
    out = run(desk, job, Scripted(no))
    assert out["flag"] is None and stored_flag(deps)["review"] is None
    # A re-triage clears the old review; a decided flag can't be reviewed.
    review(desk, flag_id, no)
    assert stored_flag(deps)["agents_disagree"]
    triage(desk, double_spend)
    assert (stored_flag(deps)["review"], stored_flag(deps)["agents_disagree"]) == (None, False)
    app_client.post(f"/v1/flags/{flag_id}/reject", json={}, headers=OPERATOR)
    with pytest.raises(Exception, match="rejected"):
        review(desk, flag_id, no)


def test_after_review_is_deterministic():
    flagged, dismissed = {"kind": "cap_drain"}, {"kind": "none"}
    droid = {"status": "succeeded", "runner": "droid"}
    assert after_review(flagged, "open", {**droid, "verdict": "agree"}) == ("open", False)
    assert after_review(dismissed, "dismissed", {**droid, "verdict": "disagree"}) == ("open", True)
    assert after_review(dismissed, "open", {**droid, "verdict": "agree"}) == ("dismissed", False)  # a 2nd review
    assert after_review(flagged, "open", {**droid, "verdict": "insufficient_evidence"}) == ("open", True)
    assert after_review(flagged, "open", {**droid, "status": "failed", "verdict": None}) == ("open", False)
    assert after_review(flagged, "open", {"status": "succeeded", "runner": "fake", "verdict": "disagree"}) == \
        ("open", False)
    assert after_review(flagged, "approved", {**droid, "verdict": "disagree"}) == ("approved", False)
    assert after_review(flagged, "invalid", {**droid, "verdict": "disagree"}) == ("invalid", False)


def test_triage_is_followed_by_a_review_when_switched_on(deps, double_spend, monkeypatch):
    seen = []
    monkeypatch.setattr(deps.events, "publish", lambda e, d: seen.append((e, d)))
    on = dataclasses.replace(deps, settings=dataclasses.replace(deps.settings, stormdesk_review=True))
    out = run(StormDesk(on), Job("triage", candidate_id=double_spend["candidate_id"]))
    assert out["review"]["job"] == "review" and out["review"]["output"]["verdict"] == "agree"
    assert out["flag"]["review"]["run_id"] == out["review"]["run_id"]
    subjects = {d["subject"] for e, d in seen if e == "stormdesk_step"}
    assert subjects == {f"candidate #{double_spend['candidate_id']}", f"review of candidate #{double_spend['candidate_id']}"}
    assert [e for e, _ in seen].count("flag") == 2  # the triage's flag, then the reviewed one
    # Off (bare Settings, or STORMDESK_REVIEW=0): one run per triage.
    out = run(StormDesk(deps), Job("triage", candidate_id=double_spend["candidate_id"]))
    assert "review" not in out
    # An invalid flag never reaches a person, so it isn't reviewed.
    out = run(StormDesk(on), Job("triage", candidate_id=double_spend["candidate_id"]),
              Scripted(flag(evidence_ids=["cd" * 32])))
    assert out["flag"]["status"] == "invalid" and "review" not in out


def test_settings_switch():
    from stormcash.config import load_settings

    def env(**extra):
        import os

        saved = dict(os.environ)
        os.environ.update({"DATABASE_URL": "postgresql://x", "SERVER_SIGNING_KEY_PEM": _pem(), **extra})
        try:
            return load_settings(env_file=None).stormdesk_review
        finally:
            os.environ.clear()
            os.environ.update(saved)

    assert env() is True and env(STORMDESK_REVIEW="0") is False


def _pem() -> str:
    from cryptography.hazmat.primitives import serialization

    from .conftest import SERVER_KEY

    return SERVER_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()


def test_a_droid_review_records_model_prompt_credits_and_duration(deps, double_spend, monkeypatch):
    from datetime import timedelta

    from droid_sdk import RunSuccess, Usage

    desk = StormDesk(deps)
    flag_id = triage(desk, double_spend)["flag"]["flag_id"]
    answer = Review(verdict="agree", reasons=["Pool money from a caught cheater."],
                    evidence_ids=[cheat_id(double_spend)]).model_dump()
    opened = patch_droid(monkeypatch, models=["claude-sonnet-5-5"], results=[RunSuccess(
        text="", messages=(), usage=Usage(input_tokens=300, output_tokens=120, cache_creation_tokens=0,
                                          cache_read_tokens=50, thinking_tokens=0, factory_credits=2100.0),
        duration=timedelta(seconds=4), turn_count=3, session_id="droid-r1", structured_output=answer)])
    live = dataclasses.replace(deps, settings=dataclasses.replace(deps.settings, stormdesk_model="claude-sonnet-5-5"))
    out = asyncio.run(StormDesk(live).review(flag_id=flag_id, runner=runner.DroidRunner(live)))
    assert (out["runner"], out["status"], out["model"], out["session_id"]) == ("droid", "succeeded",
                                                                               "claude-sonnet-5-5", "droid-r1")
    assert out["usage"]["factory_credits"] == 2100.0 and out["prompt_version"] == REVIEW_PROMPT_VERSION == 1
    assert out["duration_s"] is not None and out["duration_s"] >= 0
    # Its own system prompt; the same read-only tools, built-ins off.
    config = opened[0]["config"]
    assert config.system_prompt.startswith("You are the StormDesk reviewer") and "Execute" in config.disabled_tools
    assert opened[0]["interactions"].on_permission is not None
    with deps.pool.connection() as conn:
        row = one(conn, "SELECT * FROM stormdesk_runs WHERE job = 'review'")
    assert row["session_id"] == "droid-r1" and row["transcript"]["usage"]["factory_credits"] == 2100.0
    assert row["transcript"]["prompt_version"] == 1 and row["transcript"]["model"] == "claude-sonnet-5-5"
    f = stored_flag(deps)
    assert f["review"]["usage"]["factory_credits"] == 2100.0 and f["review"]["model"] == "claude-sonnet-5-5"


def test_the_reviewer_sees_the_proposal_not_the_first_run(deps, double_spend):
    desk = StormDesk(deps)
    proposal = flag(subject_id=subject(deps, double_spend), evidence_ids=[cheat_id(double_spend)],
                    reasoning="- pool money from a caught cheater")
    flag_id = triage(desk, double_spend, proposal)["flag"]["flag_id"]
    reviewer = Scripted(Review(verdict="agree", reasons=["r"], evidence_ids=[]))
    asyncio.run(desk.review(flag_id=flag_id, runner=reviewer))
    assert '"reasoning": "- pool money from a caught cheater"' in reviewer.prompt  # the structured output
    assert "get_candidate" in reviewer.prompt and "s-1" not in reviewer.prompt and "steps" not in reviewer.prompt


# API ---------------------------------------------------------------------------------------------


def test_review_endpoint_on_a_stored_flag(app_client, double_spend):
    out = app_client.post("/v1/stormdesk/run", json={"candidate_id": double_spend["candidate_id"]},
                          headers=OPERATOR).json()
    flag_id = out["flag"]["flag_id"]
    assert app_client.post("/v1/stormdesk/review", json={"flag_id": flag_id}).status_code == 401
    assert app_client.post("/v1/stormdesk/review", json={}, headers=OPERATOR).status_code == 400
    assert app_client.post("/v1/stormdesk/review", json={"flag_id": 999}, headers=OPERATOR).status_code == 404
    r = app_client.post("/v1/stormdesk/review", json={"flag_id": flag_id}, headers=OPERATOR).json()
    assert r["output"]["verdict"] == "agree" and r["flag"]["review"]["run_id"] == r["run_id"]
    detail = app_client.get(f"/v1/flags/{flag_id}").json()
    assert detail["flag"]["review"]["verdict"] == "agree" and detail["flag"]["agents_disagree"] is False
    assert app_client.get("/v1/flags").json()[0]["review"]["verdict"] == "agree"
    runs = app_client.get(f"/v1/stormdesk/runs?candidate_id={double_spend['candidate_id']}").json()
    assert [r["job"] for r in runs] == ["review", "triage"]
    replay = app_client.get(f"/v1/stormdesk/runs/{runs[0]['run_id']}").json()
    assert replay["transcript"]["steps"][0]["tool"] == "get_candidate"


def test_review_endpoint_on_a_proposal_passed_in(app_client, deps, double_spend):
    """How an eval reviews stored StormDesk outputs: the Flag JSON (extra keys like `_run` ignored) and its
    candidate. The run is stored; `flags` isn't touched; `after_review` is where the flag would go."""
    cand = double_spend["candidate_id"]
    stored = {**flag(kind="none", severity="info", proposed_action="none", subject_id=subject(deps, double_spend))
              .model_dump(), "_run": {"runner": "droid", "run_id": 7}}
    r = app_client.post("/v1/stormdesk/review", json={"candidate_id": cand, "proposal": stored}, headers=OPERATOR)
    body = r.json()
    assert r.status_code == 200 and body["job"] == "review" and "flag" not in body
    assert body["after_review"] == {"status": "dismissed", "agents_disagree": False, "kind": "none",
                                    "proposed_action": "none"}  # the fake reviewer's disagreement doesn't count
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM flags") == 0
        assert scalar(conn, "SELECT transcript->'reviewed'->'proposal'->>'kind' FROM stormdesk_runs") == "none"
    bad = flag(subject_id="x", evidence_ids=["cd" * 32]).model_dump()
    assert app_client.post("/v1/stormdesk/review", json={"candidate_id": cand, "proposal": bad},
                           headers=OPERATOR).status_code == 409  # never reaches a person: nothing to review
    assert app_client.post("/v1/stormdesk/review", json={"candidate_id": cand, "proposal": {"kind": "x"}},
                           headers=OPERATOR).status_code == 400
    assert app_client.post("/v1/stormdesk/review", json={"flag_id": 1, "proposal": stored},
                           headers=OPERATOR).status_code == 400


# What a run records for the Droid console: attempts and permission denials ---------------------


def test_a_droid_run_records_its_attempts_and_what_the_permission_handler_refused(deps, double_spend, monkeypatch):
    from datetime import timedelta

    import droid_sdk
    from droid_sdk import PermissionRequest, RunFailure, RunSuccess, ToolConfirmationOutcome, ToolUseBlock
    from droid_sdk.permissions import ExecuteAction, McpToolAction

    use = ToolUseBlock(id="t1", name="Execute", input={})
    shell = ExecuteAction(tool_use=use, command="curl x", full_command="curl x", impact_level="high")
    other = McpToolAction(tool_use=use, tool_name="mcp__evil__wire", impact_level="high", server_name="evil",
                          actual_tool_name="wire")
    ours = McpToolAction(tool_use=use, tool_name="mcp__stormdesk__get_case", impact_level="low",
                         server_name="stormdesk", actual_tool_name="get_case")
    answer = Review(verdict="agree", reasons=["r"], evidence_ids=[]).model_dump()
    results = [RunFailure(subtype="error_structured_output", text="", messages=(), usage=None,
                          duration=timedelta(0), turn_count=1, session_id="droid-1"),
               RunSuccess(text="", messages=(), usage=None, duration=timedelta(0), turn_count=1,
                          session_id="droid-2", structured_output=answer)]
    answers = []

    class Session:
        def __init__(self, **kw):
            self.on_permission = kw["interactions"].on_permission

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, prompt, output, timeout):
            session = self

            class Stream:
                result = results.pop(0)

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if not answers:  # the agent tries a shell command and another server's tool once
                        for request in ([shell], [ours, other], [ours]):
                            answers.append(session.on_permission(PermissionRequest(actions=request, options=[])))
                    raise StopAsyncIteration

            return Stream()

    monkeypatch.setattr(droid_sdk, "Session", Session)
    desk = StormDesk(deps)
    flag_id = triage(desk, double_spend)["flag"]["flag_id"]
    out = asyncio.run(desk.review(flag_id=flag_id, runner=runner.DroidRunner(deps)))
    assert out["status"] == "succeeded"
    assert [a.selected_option for a in answers] == [ToolConfirmationOutcome.CANCEL, ToolConfirmationOutcome.CANCEL,
                                                    ToolConfirmationOutcome.PROCEED_ONCE]
    with deps.pool.connection() as conn:
        transcript = scalar(conn, "SELECT transcript FROM stormdesk_runs WHERE job = 'review'")
        triage_transcript = scalar(conn, "SELECT transcript FROM stormdesk_runs WHERE job = 'triage'")
    assert transcript["attempts"] == [{"attempt": 1, "ok": False, "error": "error_structured_output: no output"},
                                      {"attempt": 2, "ok": True, "error": None}]
    assert transcript["permission_denials"] == [
        {"tool": "Execute", "server": None, "reason": "StormDesk may only use its read-only tools"},
        {"tool": "mcp__evil__wire", "server": "evil", "reason": "StormDesk may only use its read-only tools"}]
    # The fake runner has no attempts or permission handler: the keys are absent ("not recorded"), never zero.
    assert "attempts" not in triage_transcript and "permission_denials" not in triage_transcript


def test_a_clean_droid_run_records_one_attempt_and_no_denials(deps, double_spend, monkeypatch):
    from datetime import timedelta

    from droid_sdk import RunSuccess

    desk = StormDesk(deps)
    flag_id = triage(desk, double_spend)["flag"]["flag_id"]
    patch_droid(monkeypatch, [RunSuccess(text="", messages=(), usage=None, duration=timedelta(0), turn_count=1,
                                         session_id="droid-1",
                                         structured_output=Review(verdict="agree", reasons=[], evidence_ids=[])
                                         .model_dump())])
    asyncio.run(desk.review(flag_id=flag_id, runner=runner.DroidRunner(deps)))
    with deps.pool.connection() as conn:
        transcript = scalar(conn, "SELECT transcript FROM stormdesk_runs WHERE job = 'review'")
    assert transcript["attempts"] == [{"attempt": 1, "ok": True, "error": None}]
    assert transcript["permission_denials"] == []
