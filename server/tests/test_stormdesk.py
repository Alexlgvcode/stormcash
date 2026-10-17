"""WS5 #27: StormDesk tools, runners, citation check, storage, worker and API (spec §14)."""

from __future__ import annotations

import asyncio

import pytest

from stormcash import detectors
from stormcash.db import all_rows, one, scalar
from stormcash.stormdesk import citations, runner, tools
from stormcash.stormdesk.runner import FakeRunner, Job, RunOutcome, Steps
from stormcash.stormdesk.schemas import CaseFile, Flag
from stormcash.stormdesk.service import StormDesk
from stormcash.stormdesk.worker import Worker, pending_jobs

from .world import GAS, PHARMACY, World

OPERATOR = {"X-SC-Operator": "test"}


@pytest.fixture
def world(app_client) -> World:
    return World(app_client)


@pytest.fixture
def double_spend(world, deps):
    """A SAME_COUNTER case at the Gas Station and a merchant_silence candidate for it."""
    honest = world.pay("pharmacy", 1500)
    world.rollback()
    cheat = world.pay("gas_station", 1500)  # $5 escrow + $10 pool
    world.sync(PHARMACY, [honest])
    world.sync(GAS, [cheat])
    with deps.pool.connection() as conn:
        conn.execute("UPDATE merchants SET x = 10, y = 10")
        rows = detectors.merchant_silence(conn, (cheat.det.ts // 3600 + 1) * 3600)
        case_id = scalar(conn, "SELECT case_id FROM cases")
    assert rows, "expected a merchant_silence candidate"
    return {"case_id": case_id, "candidate_id": rows[0]["candidate_id"], "honest": honest, "cheat": cheat}


def run(desk: StormDesk, job: Job, r=None) -> dict:
    return asyncio.run(desk.run(job, r))


# Tools ---------------------------------------------------------------------------------------


def test_tools_are_read_only_and_return_citable_hex(deps, double_spend):
    case = tools.call(deps, "get_case", {"case_id": double_spend["case_id"]})
    assert case["rule"] == "SAME_COUNTER" and len(case["tag_a"]) == 64
    check = tools.call(deps, "verify_tags", {"tag_hashes": [case["tag_a"], case["tag_b"]]})
    assert all(t["signature_valid"] for t in check["tags"])
    assert check["pairs"][0]["rules_broken"] == ["SAME_COUNTER"]
    chain = tools.call(deps, "get_cert_chain", {"cert_id": case["cert_id"]})
    assert [t["counter"] for t in chain["tags"]] == [1, 1] and chain["status"] == "frozen"
    cand = tools.call(deps, "get_candidate", {"candidate_id": double_spend["candidate_id"]})
    assert cand["kind"] == "merchant_silence" and cand["subject_name"] == "Gas Station"
    pays = tools.call(deps, "get_merchant_payments", {"merchant_id": cand["subject_id"]})
    assert pays["payments"][0]["funded_pool_cents"] == 1000
    assert tools.call(deps, "get_region_status", {"region_id": "asheville-downtown"})["active_certs"] == 1
    assert tools.call(deps, "query_features", {"entity": "merchant", "id": cand["subject_id"]})["source"] == \
        "postgres_fallback"
    assert tools.call(deps, "get_nessie_balances", {"entity_id": cand["subject_id"]})["nessie_cents"] == 1500
    assert tools.call(deps, "get_messages", {"merchant_id": cand["subject_id"]})["messages"] == []
    assert len(tools.TOOLS) == 11
    with pytest.raises(tools.ToolError):
        tools.call(deps, "get_case", {"case_id": 999})


def test_tools_cannot_write(deps, double_spend):
    import psycopg

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with deps.pool.connection() as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("DELETE FROM cases")


def test_citation_check(deps, double_spend):
    h = double_spend["honest"].tag.tag_hash.hex()
    with deps.pool.connection() as conn:
        assert citations.citations_valid(conn, [h, f"tag:{h.upper()}"], required=True) == (True, [])
        assert citations.citations_valid(conn, [h, "ab" * 32], required=True) == (False, ["ab" * 32])
        assert citations.citations_valid(conn, [], required=True) == (False, [])
        assert citations.citations_valid(conn, [], required=False) == (True, [])
        assert citations.citations_valid(conn, ["no-such-alert"], required=True)[0] is False
        # get_case hands the agent the case's proof item id, so citing it is fine (seen on the first live run).
        proof = scalar(conn, "SELECT evidence->>'proof_item_id' FROM cases WHERE case_id = %s",
                       (double_spend["case_id"],))
        assert citations.citations_valid(conn, [proof, f"proof:{proof}"], required=True) == (True, [])


# Droid harness pieces (no CLI needed) --------------------------------------------------------------


def test_permission_handler_allows_only_our_tools():
    from droid_sdk import PermissionRequest, ToolConfirmationOutcome, ToolUseBlock
    from droid_sdk.permissions import ExecuteAction, McpToolAction

    use = ToolUseBlock(id="t1", name="x", input={})

    def decide(*actions):
        return runner.permission_handler(PermissionRequest(actions=list(actions), options=[])).selected_option

    ours = McpToolAction(tool_use=use, tool_name="mcp__stormdesk__get_case", impact_level="low",
                         server_name="stormdesk", actual_tool_name="get_case")
    other_server = McpToolAction(tool_use=use, tool_name="mcp__evil__wire", impact_level="high",
                                 server_name="evil", actual_tool_name="wire")
    fake_name = McpToolAction(tool_use=use, tool_name="mcp__stormdesk__transfer", impact_level="high",
                              server_name="stormdesk", actual_tool_name="transfer")
    shell = ExecuteAction(tool_use=use, command="rm -rf /", full_command="rm -rf /", impact_level="high")
    assert decide(ours) is ToolConfirmationOutcome.PROCEED_ONCE
    for bad in (other_server, fake_name, shell):
        assert decide(bad) is ToolConfirmationOutcome.CANCEL
    assert decide(ours, shell) is ToolConfirmationOutcome.CANCEL
    assert decide() is ToolConfirmationOutcome.CANCEL


def test_droid_tools_and_session_config_build(deps):
    built = [runner.droid_tool(deps, spec) for spec in tools.TOOLS]
    schemas = {t.name: t.input_schema for t in built}
    assert set(schemas["get_device_log"]["properties"]) == {"device_id", "since", "until"}
    assert list(schemas["get_device_log"]["required"]) == ["device_id"]
    assert set(schemas["verify_tags"]["properties"]) == {"tag_hashes"}
    config = runner.session_config(deps)
    assert config.disable_builtin_skills and "Execute" in config.disabled_tools
    assert config.system_prompt.startswith("You are StormDesk")
    result = asyncio.run(built[0].handler({"case_id": 999}))  # tool errors go back to the agent, not up
    assert "no case 999" in result.content


def test_runner_selection(deps):
    import dataclasses

    from stormcash.stormdesk.runner import DroidRunner, make_runner

    assert isinstance(make_runner(deps), FakeRunner)  # no FACTORY_API_KEY or droid CLI here
    deps2 = dataclasses.replace(deps, settings=dataclasses.replace(deps.settings, stormdesk_runner="droid"))
    assert isinstance(make_runner(deps2), DroidRunner)


def test_builtin_tools_are_the_verified_droid_list():
    # From Session.list_tools() against droid CLI 0.244.0 (§14.2); every one is switched off.
    assert {"Execute", "ApplyPatch", "FetchUrl", "WebSearch", "Script", "Task", "GenerateDroid"} <= runner.BUILTIN_TOOLS
    assert len(runner.BUILTIN_TOOLS) == 34


def patch_droid(monkeypatch, results: list, models: list[str] | None = None) -> list:
    """Replace droid_sdk.Session with one that streams no events and ends with each result in turn,
    on the given models (what Factory reports in the session's settings)."""
    from types import SimpleNamespace

    import droid_sdk

    opened = []

    class Stream:
        def __init__(self, result) -> None:
            self.result = result

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class Session:
        def __init__(self, **kw):
            opened.append(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, prompt, output, timeout):
            return Stream(results[len(opened) - 1])

        @property
        def settings(self):
            if models is None:
                raise AttributeError("settings")
            return SimpleNamespace(model=models[len(opened) - 1])

    monkeypatch.setattr(droid_sdk, "Session", Session)
    return opened


def test_droid_out_of_credits_is_unavailable_not_retried(deps, double_spend, monkeypatch):
    from datetime import timedelta

    from droid_sdk import ErrorEvent, ErrorType, RunFailure

    opened = patch_droid(monkeypatch, [RunFailure(
        subtype="error_during_execution", text="", messages=(), usage=None, duration=timedelta(0), turn_count=0,
        session_id="droid-1", error=ErrorEvent("Agent turn ended: model_usage_exhausted", ErrorType.ERROR))])
    outcome = asyncio.run(runner.DroidRunner(deps).run(
        Job("triage", candidate_id=double_spend["candidate_id"]), "prompt", Steps()))
    assert outcome.unavailable and outcome.output is None and outcome.session_id == "droid-1"
    assert outcome.error == "error_during_execution: Agent turn ended: model_usage_exhausted"
    assert len(opened) == 1  # no point retrying a run that couldn't start


def test_a_droid_run_records_what_it_cost(deps, double_spend, monkeypatch):
    import dataclasses
    from datetime import timedelta

    from droid_sdk import RunFailure, RunSuccess, Usage

    cand = double_spend["candidate_id"]
    with deps.pool.connection() as conn:
        subject = scalar(conn, "SELECT subject_id FROM candidates WHERE candidate_id = %s", (cand,))
    good = flag(subject_id=subject, evidence_ids=[double_spend["cheat"].tag.tag_hash.hex()]).model_dump()

    def usage(credits: float) -> Usage:
        return Usage(input_tokens=421, output_tokens=249, cache_creation_tokens=0, cache_read_tokens=100,
                     thinking_tokens=0, factory_credits=credits)

    # The first attempt's structured output fails (retried once); both attempts' costs add up. Factory moved
    # the second attempt to another model (as it does when Standard Usage runs out): the run says which.
    patch_droid(monkeypatch, models=["claude-sonnet-5-5", "droid-core"], results=[
        RunFailure(subtype="error_structured_output", text="", messages=(), usage=usage(1000.0),
                   duration=timedelta(0), turn_count=1, session_id="droid-1"),
        RunSuccess(text="", messages=(), usage=usage(2963.0), duration=timedelta(seconds=6), turn_count=3,
                   session_id="droid-2", structured_output=good),
    ])
    live = dataclasses.replace(deps, settings=dataclasses.replace(deps.settings, stormdesk_model="claude-sonnet-5-5"))
    out = run(StormDesk(live), Job("triage", candidate_id=cand), runner.DroidRunner(live))
    assert (out["runner"], out["status"]) == ("droid", "succeeded")
    assert (out["model"], out["model_requested"]) == ("droid-core", "claude-sonnet-5-5")
    assert out["usage"] == {"input_tokens": 842, "output_tokens": 498, "cache_creation_tokens": 0,
                            "cache_read_tokens": 200, "thinking_tokens": 0, "factory_credits": 3963.0}
    with deps.pool.connection() as conn:
        row = one(conn, "SELECT * FROM stormdesk_runs")
        agent = scalar(conn, "SELECT agent_transcript FROM flags")
    assert row["session_id"] == "droid-2"
    assert row["transcript"]["usage"]["factory_credits"] == agent["usage"]["factory_credits"] == 3963.0
    assert row["transcript"]["model"] == agent["model"] == "droid-core"


class DownDroid:
    """Stands in for DroidRunner when Factory says the account is out of credits."""

    name = "droid"

    def __init__(self, deps=None) -> None:
        self.calls = 0

    async def run(self, job, prompt, steps):
        self.calls += 1
        return RunOutcome("droid", None, "droid-1", "error_during_execution: Agent turn ended: model_usage_exhausted",
                          unavailable=True)


def test_unavailable_droid_falls_back_to_the_labelled_fake_runner(deps, double_spend, monkeypatch):
    from stormcash.stormdesk import service

    down = DownDroid()
    monkeypatch.setattr(service, "make_runner", lambda deps: down)
    desk = StormDesk(deps)
    out = run(desk, Job("triage", candidate_id=double_spend["candidate_id"]))
    assert (out["runner"], out["status"]) == ("fake", "succeeded")  # a usable, labelled flag, not an invalid one
    assert out["flag"]["summary"].startswith("Fake runner:") and out["flag"]["status"] == "open"
    assert "model_usage_exhausted" in out["fallback_from_droid"]
    with deps.pool.connection() as conn:
        row = one(conn, "SELECT * FROM stormdesk_runs")
    assert row["runner"] == "fake" and "model_usage_exhausted" in row["transcript"]["fallback_from_droid"]
    assert row["transcript"]["steps"][0]["tool"] == "get_candidate"
    # During the cool-down Droid isn't tried again; afterwards it is.
    run(desk, Job("investigate", case_id=double_spend["case_id"]))
    assert down.calls == 1
    desk.droid_down_until = 0
    run(desk, Job("investigate", case_id=double_spend["case_id"]))
    assert down.calls == 2


def test_droid_that_raises_falls_back_too(deps, double_spend):
    class Crashing:
        name = "droid"

        async def run(self, job, prompt, steps):
            raise FileNotFoundError("droid")

    out = run(StormDesk(deps), Job("investigate", case_id=double_spend["case_id"]), Crashing())
    assert (out["runner"], out["status"]) == ("fake", "succeeded")
    assert out["fallback_from_droid"] == "FileNotFoundError: droid"


# Running jobs ------------------------------------------------------------------------------------


def test_fake_runner_investigates_a_hard_case(deps, double_spend):
    desk = StormDesk(deps)
    out = run(desk, Job("investigate", case_id=double_spend["case_id"]))
    assert (out["runner"], out["status"], out["citations_valid"]) == ("fake", "succeeded", True)
    case_file = CaseFile.model_validate(out["output"])
    assert case_file.verified_independently and case_file.rule == "SAME_COUNTER"
    assert {"merchant": "Gas Station", "amount_cents": 1000, "source": "pool"} in case_file.who_paid
    assert out["case_file_md"].startswith("**Fake runner (no Droid)")
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT case_file_md FROM cases") == out["case_file_md"]
        run_row = one(conn, "SELECT * FROM stormdesk_runs")
    assert [s["tool"] for s in run_row["transcript"]["steps"]] == ["get_case", "verify_tags", "get_cert_chain"]
    assert all(s["ok"] for s in run_row["transcript"]["steps"])


def test_fake_runner_triages_a_candidate_with_the_rules_only_baseline(deps, double_spend, monkeypatch):
    seen = []
    monkeypatch.setattr(deps.events, "publish", lambda e, d: seen.append((e, d)))
    out = run(StormDesk(deps), Job("triage", candidate_id=double_spend["candidate_id"]))
    flag = out["flag"]
    assert (flag["status"], flag["kind"], flag["proposed_action"], flag["citations_valid"]) == (
        "open", "merchant_silence", "hold_pool_payout", True)
    assert flag["summary"].startswith("Fake runner:")
    assert flag["agent_session_id"].startswith("fake-")
    assert flag["evidence_ids"] == [double_spend["cheat"].tag.tag_hash.hex()]
    steps = [d for e, d in seen if e == "stormdesk_step"]
    assert steps[0]["tool"] == "get_candidate" and steps[-1]["done"] and steps[-1]["runner"] == "fake"
    assert any(e == "flag" for e, _ in seen)
    # Re-running updates the one flag for this candidate.
    run(StormDesk(deps), Job("triage", candidate_id=double_spend["candidate_id"]))
    with deps.pool.connection() as conn:
        assert scalar(conn, "SELECT count(*) FROM flags") == 1


def test_fake_triage_reads_features_back_and_says_from_where(deps, double_spend, monkeypatch):
    import dataclasses

    from stormcash import chalk_features

    out = run(StormDesk(deps), Job("triage", candidate_id=double_spend["candidate_id"]))
    with deps.pool.connection() as conn:
        steps = one(conn, "SELECT transcript FROM stormdesk_runs")["transcript"]["steps"]
        window_end = scalar(conn, "SELECT window_end FROM candidates")
    assert [s["tool"] for s in steps][:2] == ["get_candidate", "query_features"]
    assert steps[1]["ok"] and steps[1]["input"] == {"entity": "merchant", "id": out["flag"]["subject_id"], "as_of": window_end}
    assert "Postgres fallback" in out["output"]["reasoning"] and "CHALK_DISABLED" in out["output"]["reasoning"]

    asked = []

    def chalk(settings, entity, id, features, as_of):
        asked.append((entity, id, as_of))
        return {"source": "chalk", "entity": entity, "id": id, "as_of": as_of, "latency_ms": 212,
                "features": {"silence_ratio_6h": 0.1176, "pool_funded_cents_6h": 1000}}

    monkeypatch.setattr(chalk_features, "query", chalk)
    on = dataclasses.replace(deps, settings=dataclasses.replace(deps.settings, chalk_enabled=True))
    out = run(StormDesk(on), Job("triage", candidate_id=double_spend["candidate_id"]))
    assert asked == [("merchant", out["flag"]["subject_id"], window_end)]
    assert "Chalk at the window end: silence_ratio_6h 0.1176, pool_funded_cents_6h 1000 (212 ms)" \
        in out["output"]["reasoning"]
    assert out["flag"]["proposed_action"] == "hold_pool_payout"  # reported, not weighed: still the baseline


class Scripted:
    """A stand-in agent that returns a fixed output."""

    name = "test"

    def __init__(self, output=None, error: Exception | None = None):
        self.output, self.error = output, error

    async def run(self, job: Job, prompt: str, steps: Steps) -> RunOutcome:
        steps.call("get_candidate", {"candidate_id": job.candidate_id})
        if self.error:
            raise self.error
        return RunOutcome(self.name, self.output, "s-1")


def flag(**overrides) -> Flag:
    values = dict(kind="merchant_silence", severity="urgent", subject_id="x", evidence_ids=[], exposure_cents=0,
                  summary="s", reasoning="r", proposed_action="hold_pool_payout")
    return Flag(**{**values, **overrides})


def test_invented_ids_make_the_flag_invalid(deps, double_spend):
    out = run(StormDesk(deps), Job("triage", candidate_id=double_spend["candidate_id"]),
              Scripted(flag(evidence_ids=["cd" * 32])))
    assert out["status"] == "invalid" and out["missing_citations"] == ["cd" * 32]
    assert out["flag"]["status"] == "invalid" and out["flag"]["citations_valid"] is False


def test_a_dismissal_needs_no_ids_but_a_flag_does(deps, double_spend):
    desk = StormDesk(deps)
    out = run(desk, Job("triage", candidate_id=double_spend["candidate_id"]),
              Scripted(flag(kind="none", proposed_action="none")))
    assert out["flag"]["status"] == "dismissed"
    out = run(desk, Job("triage", candidate_id=double_spend["candidate_id"]), Scripted(flag()))
    assert out["flag"]["status"] == "invalid"  # a real flag with no evidence isn't actionable


def test_a_failed_run_is_stored_not_raised(deps, double_spend):
    out = run(StormDesk(deps), Job("triage", candidate_id=double_spend["candidate_id"]),
              Scripted(error=ConnectionError("droid exited")))
    assert out["status"] == "failed" and "droid exited" in out["error"]
    assert out["flag"]["status"] == "invalid"


def test_operator_decisions_are_never_overwritten(deps, double_spend):
    desk = StormDesk(deps)
    run(desk, Job("triage", candidate_id=double_spend["candidate_id"]))
    with deps.pool.connection() as conn:
        conn.execute("UPDATE flags SET status = 'approved'")
    with pytest.raises(Exception, match="already approved"):
        run(desk, Job("triage", candidate_id=double_spend["candidate_id"]))


def test_worker_picks_up_new_cases_and_candidates_once(deps, double_spend):
    desk = StormDesk(deps)
    assert {(j.kind, j.case_id or j.candidate_id) for j in pending_jobs(deps)} == {
        ("investigate", double_spend["case_id"]), ("triage", double_spend["candidate_id"])}

    async def drain():
        worker = Worker(desk)
        assert await worker.tick() == 2
        while worker.inflight:
            await asyncio.sleep(0.01)
        return await worker.tick()

    assert asyncio.run(drain()) == 0
    assert pending_jobs(deps) == []


# API -------------------------------------------------------------------------------------------------


def test_run_endpoint_flags_and_runs(app_client, double_spend):
    assert app_client.post("/v1/stormdesk/run", json={"case_id": double_spend["case_id"]}).status_code == 401
    assert app_client.post("/v1/stormdesk/run", json={}, headers=OPERATOR).status_code == 400
    out = app_client.post("/v1/stormdesk/run", json={"candidate_id": double_spend["candidate_id"]},
                          headers=OPERATOR).json()
    assert out["flag"]["kind"] == "merchant_silence"
    app_client.post("/v1/stormdesk/run", json={"case_id": double_spend["case_id"]}, headers=OPERATOR)
    flags = app_client.get("/v1/flags").json()
    assert [(f["kind"], f["runner"]) for f in flags] == [("merchant_silence", "fake")]
    detail = app_client.get(f"/v1/flags/{flags[0]['flag_id']}").json()
    assert detail["candidate"]["kind"] == "merchant_silence" and detail["agent"]["steps"]
    runs = app_client.get("/v1/stormdesk/runs").json()
    assert [r["job"] for r in runs] == ["investigate", "triage"]
    replay = app_client.get(f"/v1/stormdesk/runs/{runs[0]['run_id']}").json()
    assert replay["transcript"]["steps"][0]["tool"] == "get_case"
    assert app_client.post("/v1/stormdesk/run", json={"case_id": 999}, headers=OPERATOR).status_code == 404


def test_reset_clears_stormdesk_output_for_real_devices(app_client, deps, double_spend):
    app_client.post("/v1/stormdesk/run", json={"candidate_id": double_spend["candidate_id"]}, headers=OPERATOR)
    app_client.post("/v1/stormdesk/run", json={"case_id": double_spend["case_id"]}, headers=OPERATOR)
    assert app_client.post("/v1/demo/reset", headers=OPERATOR).json()["ok"]
    with deps.pool.connection() as conn:
        assert [scalar(conn, f"SELECT count(*) FROM {t}") for t in ("flags", "stormdesk_runs", "candidates")] == [0, 0, 0]
        assert all_rows(conn, "SELECT * FROM cases") == []
