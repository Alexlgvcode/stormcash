"""The StormDesk eval pieces (chalk/evals), offline: no Chalk calls, no deploys.

CHALK_REMOTE_FUNCTION=1 makes @chalkcompute.function return the plain function
(what a Chalk worker sees), so importing the scorers and tasks deploys nothing.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import urllib.error
import urllib.request

import pytest

os.environ["CHALK_REMOTE_FUNCTION"] = "1"
EVALS = Path(__file__).resolve().parents[1] / "evals"
sys.path.insert(0, str(EVALS))

import eval_scorers  # noqa: E402
import gateway  # noqa: E402
import results  # noqa: E402
import task_replay  # noqa: E402
import task_rules_only  # noqa: E402

SCENARIOS = {"colluder", "stolen_phone", "dark_region", "trap_remote_shop", "trap_victim_shop", "trap_stockup",
             "trap_clock_drift", "trap_quiet_region", "honest"}


def flag(**over) -> dict:
    base = {"kind": "merchant_silence", "severity": "review", "subject_id": "ab" * 16, "evidence_ids": ["cd" * 32],
            "exposure_cents": 2000, "summary": "s", "reasoning": "- r", "proposed_action": "hold_pool_payout",
            "action_params": {}, "merchant_notice": None}
    return {**base, **over}


def out(f: dict, **run) -> str:
    return json.dumps({**f, "_run": run} if run else f)


def score(result):
    return [r.score for r in result] if isinstance(result, list) else result.score


# Flag parsing ---------------------------------------------------------------------------------

PARSE_CASES = [
    out(flag()), out(flag(kind="none", proposed_action="none")), "not json", "", None, "[]", "{}",
    out(flag(kind="hard_case")), out(flag(severity="high")), out(flag(proposed_action="refund")),
    out(flag(evidence_ids="x")), out(flag(exposure_cents="12")),
    gateway.to_output({"runner": "droid", "status": "failed", "output": None, "error": "boom"}),
]


@pytest.mark.parametrize("output", PARSE_CASES)
def test_scorers_and_results_parse_flags_the_same_way(output):
    assert eval_scorers.parse_flag(output) == results.parse_flag(output)


def test_parse_flag_accepts_only_flags():
    assert eval_scorers.parse_flag(out(flag(), runner="fake"))["kind"] == "merchant_silence"
    assert [eval_scorers.parse_flag(o) is None for o in PARSE_CASES] == [False, False] + [True] * 11


# Scorers ---------------------------------------------------------------------------------------

def test_kind_and_action_correct():
    good = out(flag())
    assert score(eval_scorers.kind_correct(good, "merchant_silence")) == 1.0
    assert score(eval_scorers.kind_correct(good, "none")) == 0.0
    assert score(eval_scorers.action_correct(good, "hold_pool_payout")) == 1.0
    assert score(eval_scorers.action_correct(good, "none")) == 0.0
    assert score(eval_scorers.kind_correct("StormDesk produced no Flag", "none")) == 0.0
    assert score(eval_scorers.action_correct("StormDesk produced no Flag", "none")) == 0.0


def test_no_false_flag_applies_to_honest_rows():
    assert score(eval_scorers.no_false_flag(out(flag()), False)) == 1.0  # nothing to falsely flag
    assert eval_scorers.no_false_flag(out(flag()), False).metadata == {"applies": False}
    assert score(eval_scorers.no_false_flag(out(flag()), True)) == 0.0
    assert score(eval_scorers.no_false_flag(out(flag(kind="none", proposed_action="none")), True)) == 1.0
    info = flag(kind="region_dark", severity="info", proposed_action="none")
    assert score(eval_scorers.no_false_flag(out(info), True)) == 1.0
    assert score(eval_scorers.no_false_flag(out(flag(severity="info")), True)) == 0.0
    assert score(eval_scorers.no_false_flag("not a flag", True)) == 0.0


def test_citations_valid_uses_the_server_check():
    assert score(eval_scorers.citations_valid(out(flag(), runner="fake", citations_valid=True))) == 1.0
    assert score(eval_scorers.citations_valid(out(flag(), runner="droid", citations_valid=False,
                                                  missing_citations=["ff"]))) == 0.0
    assert score(eval_scorers.citations_valid(out(flag(), runner="rules_only", citations_valid=None))) == 0.0
    assert score(eval_scorers.citations_valid("no flag")) == 0.0
    assert "citations-valid" not in eval_scorers.RULES_ONLY_SCORERS  # the baseline cites nothing: n/a
    assert list(eval_scorers.SCORERS) == list(results.SCORERS)


# Tasks -----------------------------------------------------------------------------------------

def test_rules_only_gives_every_candidate_its_default_action():
    f = {"pool_funded_cents": 2000, "spent_15m_cents": 4300}
    for kind, action, exposure in (("merchant_silence", "hold_pool_payout", 2000),
                                   ("cap_drain", "freeze_cert", 4300), ("region_dark", "dispatch_relay", 0)):
        output = task_rules_only.rules_only(kind, "subject", json.dumps(f))
        parsed = eval_scorers.parse_flag(output)
        assert (parsed["kind"], parsed["proposed_action"], parsed["exposure_cents"]) == (kind, action, exposure)
        assert parsed["_run"] == {"runner": "rules_only", "citations_valid": None}
        assert parsed["evidence_ids"] == []


def test_replay_returns_the_output_unchanged():
    assert task_replay.replay_output("anything") == "anything"


# Gateway ---------------------------------------------------------------------------------------

RUN = {"run_id": 7, "runner": "fake", "status": "succeeded", "citations_valid": True, "missing_citations": [],
       "error": None, "fallback_from_droid": None, "output": flag(), "flag": {"flag_id": 1}}


def test_to_output_keeps_the_flag_and_the_server_verdict():
    parsed = json.loads(gateway.to_output(RUN, model="claude-sonnet-5-5"))
    assert parsed["kind"] == "merchant_silence"
    assert parsed["_run"]["runner"] == "fake" and parsed["_run"]["model"] is None  # model only for Droid runs
    assert parsed["_run"]["citations_valid"] is True
    droid = json.loads(gateway.to_output({**RUN, "runner": "droid"}, model="claude-sonnet-5-5"))
    assert droid["_run"]["model"] == "claude-sonnet-5-5"
    text = gateway.to_output({**RUN, "output": None, "status": "failed", "error": "boom"})
    assert text.startswith("StormDesk produced no Flag (runner fake, status failed)")
    with pytest.raises(ValueError):
        json.loads(text)


@pytest.fixture
def fake_server():
    seen = []
    state = {"run": RUN}

    class Server(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers["X-SC-Operator"], body))
            data = json.dumps(state["run"]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", seen, state
    httpd.shutdown()


def test_gateway_runs_jobs_behind_the_token(fake_server):
    server_url, seen, _ = fake_server
    token = "t" * 32
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), gateway.make_handler(gateway.Jobs({42: server_url}, None), token))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"

    def call(method, path, body=None, auth=token):
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": f"Bearer {auth}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        assert call("POST", "/runs", {"seed": 42, "candidate_id": 5}, auth="wrong")[0] == 401
        assert call("POST", "/v1/demo/reset", {})[0] == 404  # nothing else of the server is reachable
        assert call("POST", "/runs", {"seed": 9, "candidate_id": 5})[0] == 400
        code, job = call("POST", "/runs", {"seed": 42, "candidate_id": 5})
        assert code == 202
        for _ in range(50):
            code, state = call("GET", f"/runs/{job['job_id']}")
            if state["status"] != "running":
                break
            threading.Event().wait(0.05)
        assert state["status"] == "done"
        assert json.loads(state["output"])["_run"]["run_id"] == 7
        assert seen == [("/v1/stormdesk/run", gateway.OPERATOR, {"candidate_id": 5})]
    finally:
        httpd.shutdown()


# Results ---------------------------------------------------------------------------------------

def row(scenario, label_kind, label_action, honest, output, kind=None, pool=0, **scores):
    kind = kind or (label_kind if label_kind != "none" else "merchant_silence")
    r = {"row_id": f"1:{scenario}", "seed": 1, "candidate_id": 1, "kind": kind, "subject_id": "s",
         "subject_name": "Shop", "features": json.dumps({"pool_funded_cents": pool}), "label_kind": label_kind,
         "label_action": label_action, "label_scenario": scenario, "honest_subject": honest, "output": output,
         "output_error": None}
    for name in results.SCORERS:
        r[f"{name}_value"] = scores.get(name.replace("-", "_"))
    return r


def summarize(rows, scorers=results.SCORERS):
    return results.summarize(rows, chalk={"run_id": "r1"}, dataset={"rows": len(rows)}, mode="chalk_task",
                             git_sha=None, now=1792200000, scorers=list(scorers))


def test_rules_only_summary():
    rules = lambda kind: task_rules_only.rules_only(kind, "s", json.dumps({"pool_funded_cents": 2000}))  # noqa: E731
    rows = [
        row("colluder", "merchant_silence", "hold_pool_payout", False, rules("merchant_silence"), pool=2000),
        row("trap_victim_shop", "none", "none", True, rules("merchant_silence"), pool=2000),
        row("stolen_phone", "cap_drain", "freeze_cert", False, rules("cap_drain"), kind="cap_drain"),
    ]
    rows[0]["no-false-flag_value"], rows[1]["no-false-flag_value"], rows[2]["no-false-flag_value"] = 1.0, 0.0, 1.0
    s = summarize(rows, eval_scorers.RULES_ONLY_SCORERS)
    assert (s["runner"], s["table_column"], s["is_agent_result"]) == ("rules_only", "rules_only", False)
    assert s["scorers"]["no-false-flag"]["mean_honest_rows"] == 0.0
    assert s["scorers"]["citations-valid"]["in_evaluation"] is False
    m = s["metrics"]
    assert m["colluders_caught"] == {"caught": 1, "total": 1, "recall": 1.0}
    assert m["honest_flagged"] == {"flagged": 1, "total": 1, "false_flag_rate": 1.0}
    assert m["precision_by_kind"]["merchant_silence"] == {"flagged": 2, "correct": 1, "precision": 0.5}
    assert m["citations_valid"] is None
    assert m["pool_cents"]["held_correctly"] == 2000 and m["pool_cents"]["held_from_honest_shops"] == 2000
    assert {p["scenario"]: p["flagged"] for p in s["per_scenario"]} == {"colluder": 1, "stolen_phone": 1,
                                                                         "trap_victim_shop": 1}


def droid_out(f: dict, models=("m",), asked="m", **run) -> str:
    return out(f, runner="droid", citations_valid=True, model=asked, models_used=list(models), factory_credits=100.0,
               **run)


def test_fake_and_mixed_runs_are_never_a_stormdesk_column():
    fake = row("colluder", "merchant_silence", "hold_pool_payout", False,
               out(flag(), runner="fake", citations_valid=True))
    dismiss = flag(kind="none", proposed_action="none")
    droid = row("trap_victim_shop", "none", "none", True, droid_out(dismiss))
    fallback = row("colluder", "merchant_silence", "hold_pool_payout", False,
                   droid_out(flag(), fallback_from_droid="model_usage_exhausted"))
    assert summarize([fake])["table_column"] is None and summarize([fake])["runner"] == "fake"
    assert summarize([fake, droid])["runner"] == "mixed"
    assert summarize([droid, fallback])["runner"] == "mixed"
    s = summarize([droid])
    assert (s["runner"], s["table_column"], s["model"], s["runner_label"]) == ("droid", "stormdesk", "m",
                                                                              "StormDesk (Droid, m)")
    assert s["metrics"]["honest_flagged"]["flagged"] == 0
    assert s["metrics"]["citations_valid"] == {"valid": 1, "checked": 1, "rate": 1.0}
    assert s["metrics"]["factory_credits"]["rows_total"] == 100.0 and s["complete"] is True


def test_a_stormdesk_result_needs_one_named_model_on_every_row():
    dismiss = flag(kind="none", proposed_action="none")
    sonnet = row("trap_victim_shop", "none", "none", True, droid_out(dismiss))
    core = row("trap_stockup", "none", "none", True, droid_out(dismiss, models=("droid-core",)))
    both = row("trap_stockup", "none", "none", True, droid_out(dismiss, models=("droid-core", "m")))
    unknown = row("trap_stockup", "none", "none", True, droid_out(dismiss, models=()))
    disagree = row("trap_stockup", "none", "none", True, droid_out(dismiss, server_model="droid-core"))
    agree = row("trap_stockup", "none", "none", True, droid_out(dismiss, server_model="m"))
    assert summarize([disagree])["runner"] == "mixed" and summarize([agree])["runner"] == "droid"
    assert summarize([sonnet, core])["runner"] == "mixed"
    assert summarize([both])["runner"] == "mixed"
    assert summarize([unknown])["runner"] == "mixed"  # the model couldn't be read: not a StormDesk result
    assert summarize([core])["runner"] == "mixed"  # not the model asked for
    audit = {"tripped": None, "audit": {"models_seen": ["droid-core", "m"]}}  # a retried attempt on another model
    s = results.summarize([sonnet], chalk={}, dataset={}, mode="chalk_task", git_sha=None, now=0, droid_audit=audit)
    assert s["runner"] == "mixed" and s["table_column"] is None


def test_an_incomplete_droid_run_is_not_a_stormdesk_column():
    dismiss = flag(kind="none", proposed_action="none")
    good = row("trap_victim_shop", "none", "none", True, droid_out(dismiss))
    refused = {**row("colluder", "merchant_silence", "hold_pool_payout", False, None), "output_error": "409"}
    s = summarize([good, refused])
    assert (s["runner"], s["complete"], s["table_column"]) == ("droid", False, None)
    tripped = {"tripped": "credit cap reached", "audit": {"models_seen": ["m"]}}
    s = results.summarize([good], chalk={}, dataset={}, mode="chalk_task", git_sha=None, now=0, droid_audit=tripped)
    assert (s["complete"], s["table_column"]) == (False, None)


def test_failed_rows_count_as_failures():
    failed = row("colluder", "merchant_silence", "hold_pool_payout", False,
                 gateway.to_output({"runner": "droid", "status": "failed", "output": None, "error": "x"}))
    errored = {**row("colluder", "merchant_silence", "hold_pool_payout", False, None), "output_error": "boom"}
    s = summarize([failed, errored])
    assert s["metrics"]["rows_without_flag"] == 2 and s["metrics"]["task_errors"] == 1
    assert s["metrics"]["colluders_caught"]["caught"] == 0
    assert s["runners_seen"] == {"droid": 1}


def test_list_scorer_columns_get_their_names():
    import run_eval

    class Scorer:
        def __init__(self, id):
            self.id = id

    class Evaluation:
        scorers = [Scorer(f"s{i}") for i in range(len(results.SCORERS))]
        metadata = {}

    r = {"kind-correct_value": 1.0, "scorer_s3": [{"score": 1.0, "metadata": "{}"}], "scorer_s3_error": None,
         "scorer_s4": [], "scorer_s4_error": None}
    [named] = run_eval.named_scores([r], Evaluation())
    assert named["no-false-flag_value"] == [1.0] and named["citations-valid_value"] == []
    assert results._score(named, "no-false-flag") == 1.0 and results._score(named, "citations-valid") is None
    assert not any(k.startswith("scorer_") for k in named)


def test_list_scores_are_averaged_and_empty_lists_skipped():
    r = row("colluder", "merchant_silence", "hold_pool_payout", False, out(flag()))
    assert results._score({**r, "no-false-flag_value": []}, "no-false-flag") is None
    assert results._score({**r, "no-false-flag_value": [1.0]}, "no-false-flag") == 1.0
    assert results._score({**r, "kind-correct_value": float("nan")}, "kind-correct") is None


# The committed dataset ---------------------------------------------------------------------------

def test_dataset_rows_match_spec_columns_and_meta():
    rows = [json.loads(line) for line in (EVALS / "dataset" / "stormdesk_triage.jsonl").read_text().splitlines()]
    meta = json.loads((EVALS / "dataset" / "meta.json").read_text())
    assert len(rows) == meta["rows"] and sum(r["honest_subject"] for r in rows) == meta["honest_rows"]
    assert sorted({r["seed"] for r in rows}) == sorted(s["seed"] for s in meta["seeds"])
    reserved = {"output", "trace"}
    for r in rows:
        assert {"candidate_id", "kind", "subject_id", "features", "label_kind", "label_action", "label_scenario",
                "honest_subject"} <= r.keys()
        assert not reserved & r.keys() and not any(k.startswith("__chalk") for k in r)
        assert r["label_scenario"] in SCENARIOS
        assert r["label_kind"] in ("merchant_silence", "cap_drain", "region_dark", "none")
        assert r["honest_subject"] == (r["label_kind"] == "none")
        assert isinstance(json.loads(r["features"]), dict)
    assert len({r["row_id"] for r in rows}) == len(rows)


# Droid guard (gateway) ----------------------------------------------------------------------------

def write_session(folder: Path, session_id: str, models, credits):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{session_id}.settings.json").write_text(json.dumps(
        {"model": models[0] if models else None, "tokenUsage": {"factoryCredits": credits}}))
    lines = [{"type": "session_start"}] + [{"type": "message", "message": {"role": "assistant", "modelId": m}}
                                           for m in models]
    (folder / f"{session_id}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


SID = "951a7cbe-3064-4a45-a787-5ba432e09b8f"


def test_session_info_reads_model_and_credits(tmp_path):
    write_session(tmp_path / "-some-cwd", SID, ["claude-sonnet-5-5", "claude-sonnet-5-5"], 47054)
    info = gateway.find_session(SID, str(tmp_path))
    assert info == {"models_used": ["claude-sonnet-5-5"], "factory_credits": 47054,
                    "configured_model": "claude-sonnet-5-5"}
    assert gateway.find_session("../../etc/passwd", str(tmp_path)) is None
    assert gateway.audit(str(tmp_path / "-some-cwd"), 0) == {"sessions": 1, "factory_credits": 47054,
                                                             "models_seen": ["claude-sonnet-5-5"]}
    out_ = json.loads(gateway.to_output({**RUN, "runner": "droid", "flag": {"agent_session_id": SID}},
                                        "claude-sonnet-5-5", info))
    assert out_["_run"]["session_id"] == SID and out_["_run"]["models_used"] == ["claude-sonnet-5-5"]
    assert out_["_run"]["factory_credits"] == 47054


def run_one(jobs, seed=42, candidate_id=5):
    job_id = jobs.start(seed, candidate_id)
    for _ in range(100):
        state = jobs.get(job_id)
        if state["status"] != "running":
            return state
        threading.Event().wait(0.02)
    raise AssertionError("job never finished")


@pytest.mark.parametrize("models, credits, cap, trips", [
    (["claude-sonnet-5-5"], 1000, 10**6, None),
    (["droid-core"], 1000, 10**6, "not claude-sonnet-5-5"),
    (["claude-sonnet-5-5"], 1000, 10**6, None),
    (["claude-sonnet-5-5"], 2000, 1500, "credit cap reached"),
])
def test_breaker_refuses_rows_after_a_model_change_or_the_cap(tmp_path, fake_server, models, credits, cap, trips):
    server_url, _, state = fake_server
    sessions = tmp_path / "-eval-servers"
    write_session(sessions, SID, models, credits)
    state["run"] = {**RUN, "runner": "droid", "flag": {"agent_session_id": SID}}
    jobs = gateway.Jobs({42: server_url}, "claude-sonnet-5-5", require_model="claude-sonnet-5-5", max_credits=cap,
                        sessions_dir=str(sessions), sessions_root=str(tmp_path))
    jobs.started = 0
    assert run_one(jobs)["status"] == "done"
    if trips is None:
        assert jobs.tripped is None and run_one(jobs)["status"] == "done"
    else:
        assert trips in jobs.tripped
        with pytest.raises(gateway.Refused):
            jobs.start(42, 6)
    assert jobs.stats()["audit"]["factory_credits"] == credits


def test_breaker_trips_when_the_server_reports_another_model(tmp_path, fake_server):
    server_url, _, state = fake_server
    write_session(tmp_path / "-eval", SID, ["m"], 10)
    state["run"] = {**RUN, "runner": "droid", "flag": {"agent_session_id": SID}, "model": "droid-core",
                    "usage": {"factory_credits": 10}}
    jobs = gateway.Jobs({42: server_url}, "m", require_model="m", max_credits=10**6,
                        sessions_dir=str(tmp_path / "-eval"), sessions_root=str(tmp_path))
    done = run_one(jobs)
    assert "server says the run used droid-core" in jobs.tripped
    assert json.loads(done["output"])["_run"]["server_usage"] == {"factory_credits": 10}


def test_breaker_trips_on_a_fallback_or_a_missing_session(tmp_path, fake_server):
    server_url, _, state = fake_server
    jobs = gateway.Jobs({42: server_url}, "m", require_model="m", max_credits=10**6, sessions_dir=str(tmp_path),
                        sessions_root=str(tmp_path))
    state["run"] = {**RUN, "runner": "fake", "fallback_from_droid": "model_usage_exhausted"}
    run_one(jobs)
    assert "answered by fake" in jobs.tripped
    jobs = gateway.Jobs({42: server_url}, "m", require_model="m", max_credits=10**6, sessions_dir=str(tmp_path),
                        sessions_root=str(tmp_path))
    state["run"] = {**RUN, "runner": "droid", "flag": {"agent_session_id": SID}}  # no session files
    run_one(jobs)
    assert "no session files" in jobs.tripped
