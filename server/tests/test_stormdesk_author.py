"""Droid proposes a detector as a pull request (spec §14.7d): the sandbox confines it, our re-run checks
every claim, only a verified Droid run reaches the (mocked) PR step, and the switch is off by default."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from droid_sdk.permissions import CreateFile, EditAction, ExecuteAction, McpToolAction
from droid_sdk import PermissionRequest
from droid_sdk._high_level.messages import ToolUseBlock

from stormcash.config import load_settings
from stormcash.db import one
from stormcash.stormdesk import author, detector_eval, sandbox

from .conftest import make_settings

NAME = "region_dark_alert"
DETECTOR = f'''"""Raise a dark region only while a weather alert is active."""
KIND = "region_dark"
NAME = "{NAME}"


def fires(features: dict) -> bool:
    return bool(features.get("active_alerts"))
'''
TEST = f'''from stormcash.detectors_proposed.{NAME} import fires


def test_alert_raises():
    assert fires({{"active_alerts": [{{"event": "Flash Flood Warning"}}]}})


def test_quiet_region_does_not():
    assert not fires({{"active_alerts": []}})
'''
OS_SANDBOX = sandbox.sandbox_exec() is not None  # macOS; CI (Linux) runs the lab without the OS profile


def _use(tool: str) -> ToolUseBlock:
    return ToolUseBlock(id=f"t-{tool}", name=tool, input={})


def create(repo: Path, rel: str, content: str = "x = 1\n") -> CreateFile:
    return CreateFile(tool_use=_use("Create"), file_path=str(repo / rel), file_name=Path(rel).name, content=content)


def execute(command: str) -> ExecuteAction:
    return ExecuteAction(tool_use=_use("Execute"), full_command=command, command=command)


def ask(guard: sandbox.AuthorGuard, *actions) -> bool:
    return guard.decide(PermissionRequest(actions=list(actions), options=[]))[0]


# The permission handler ---------------------------------------------------------------------


def test_edits_outside_the_allowlist_are_denied_and_recorded(tmp_path):
    guard = sandbox.AuthorGuard(tmp_path)
    for rel in ("server/stormcash/detectors.py", "server/stormcash/settlement.py", "server/.env",
                "server/stormcash/detectors_proposed/__init__.py", "server/tests/conftest.py",
                "server/stormcash/detectors_proposed/Bad-Name.py", ".github/workflows/ci.yml"):
        assert not ask(guard, create(tmp_path, rel))
    assert not ask(guard, create(tmp_path, "../../outside.py"))
    assert not ask(guard, CreateFile(tool_use=_use("Create"), file_path="/tmp/stormdesk_detector.py",
                                     file_name="x.py", content=""))
    assert guard.name is None
    assert len(guard.denials) == 9
    assert all(d["tool"] == "Create" and d["reason"] for d in guard.denials)
    assert "not on the allowlist" in guard.denials[0]["reason"]
    assert guard.denials[-1]["reason"] == "outside the sandbox"


def test_the_first_allowed_edit_fixes_the_detector_name(tmp_path):
    guard = sandbox.AuthorGuard(tmp_path)
    assert ask(guard, create(tmp_path, f"server/stormcash/detectors_proposed/{NAME}.py", DETECTOR))
    assert guard.name == NAME
    assert ask(guard, EditAction(tool_use=_use("Edit"), file_path=str(tmp_path / f"server/tests/test_proposed_{NAME}.py"),
                                 file_name="t.py", new_content=TEST))
    assert not ask(guard, create(tmp_path, "server/stormcash/detectors_proposed/another_one.py"))
    assert not ask(guard, create(tmp_path, "server/tests/test_proposed_another_one.py"))
    assert not ask(guard, create(tmp_path, f"server/stormcash/detectors_proposed/{NAME}.py", "x" * 30_000))
    assert [d["reason"] for d in guard.denials][:2] == [f"this run's detector is {NAME}"] * 2


def test_the_shell_is_refused_whatever_the_command(tmp_path):
    guard = sandbox.AuthorGuard(tmp_path)
    ask(guard, create(tmp_path, f"server/stormcash/detectors_proposed/{NAME}.py", DETECTOR))
    for command in (f"pytest server/tests/test_proposed_{NAME}.py", "git push origin HEAD", "curl https://example.com",
                    "cat ~/.ssh/id_rsa", "ls", "python -m stormcash.stormdesk.detector_eval --detector x --data y"):
        assert not ask(guard, execute(command)), command
    assert {d["tool"] for d in guard.denials} == {"Execute"}
    assert all("no shell in the sandbox" in d["reason"] for d in guard.denials)
    assert sandbox.WRITE_TOOLS == {"Create", "Edit", "ApplyPatch"}  # Execute is switched off too


def test_the_two_commands_run_only_for_this_detector_and_within_budget(tmp_path):
    guard = sandbox.AuthorGuard(tmp_path)
    assert guard.allow_lab("test", NAME) == "write the detector and its test first, then name it"
    ask(guard, create(tmp_path, f"server/stormcash/detectors_proposed/{NAME}.py", DETECTOR))
    assert guard.allow_lab("eval", "other_name") is not None
    assert guard.allow_lab("test", NAME) is None
    for _ in range(sandbox.BUDGET["eval"]):
        assert guard.allow_lab("eval", NAME) is None
    assert guard.allow_lab("eval", NAME) == f"the eval budget ({sandbox.BUDGET['eval']} runs) is used up"
    assert [d["tool"] for d in guard.denials] == ["run_tests", "run_eval", "run_eval"]
    assert guard.used == {"test": 1, "eval": sandbox.BUDGET["eval"]}


def test_only_the_sandbox_read_tools_are_allowed(tmp_path):
    guard = sandbox.AuthorGuard(tmp_path)

    def mcp(server: str, tool: str) -> McpToolAction:
        return McpToolAction(tool_use=_use(f"mcp__{server}__{tool}"), tool_name=f"mcp__{server}__{tool}",
                             impact_level="low", server_name=server, actual_tool_name=tool)

    assert ask(guard, mcp(sandbox.LAB_SERVER_NAME, "read_file"))
    assert not ask(guard, mcp("stormdesk", "get_case"))  # the triage tools aren't the author's
    assert not ask(guard, mcp(sandbox.LAB_SERVER_NAME, "write_file"))
    assert ask(guard, mcp(sandbox.LAB_SERVER_NAME, "run_eval"))  # the tool itself checks the name and budget
    assert not ask(guard, mcp(sandbox.LAB_SERVER_NAME, "read_file"), execute("ls"))  # one bad action refuses all
    assert [d["tool"] for d in guard.denials] == ["mcp__stormdesk__get_case", "mcp__stormdesk_lab__write_file",
                                                 "mcp__stormdesk_lab__read_file", "Execute"]


def test_the_read_tools_never_serve_held_out_data_git_or_anything_outside(tmp_path):
    (tmp_path / "chalk/evals/dataset").mkdir(parents=True)
    (tmp_path / "chalk/evals/results").mkdir(parents=True)
    for name in ("stormdesk_triage.jsonl", "stormdesk_triage_heldout.jsonl", "meta_heldout.json"):
        (tmp_path / "chalk/evals/dataset" / name).write_text("{}\n")
    (tmp_path / "chalk/evals/results/run.json").write_text("{}")
    (tmp_path / ".git").write_text("gitdir: elsewhere")
    (tmp_path / "server").mkdir()
    (tmp_path / "server/.env").write_text("DATABASE_URL=secret")
    (tmp_path / "link").symlink_to("/etc")
    files = sandbox.LabFiles(tmp_path)
    assert files.read("chalk/evals/dataset/stormdesk_triage.jsonl")["text"] == "{}"
    for path in ("chalk/evals/dataset/stormdesk_triage_heldout.jsonl", "chalk/evals/dataset/meta_heldout.json",
                 "chalk/evals/results/run.json", ".git", "server/.env", "../outside", "/etc/passwd", "link/passwd"):
        assert "error" in files.read(path), path
    assert files.list("chalk/evals/dataset")["entries"] == ["chalk/evals/dataset/stormdesk_triage.jsonl"]
    assert "link" not in str(files.list(".")) and ".git" not in str(files.list("."))
    assert files.search("secret")["matches"] == []


# The evaluation script --------------------------------------------------------------------------


def test_the_eval_refuses_a_detector_that_is_not_pure():
    bad = 'import os\nKIND = "region_dark"\nNAME = "x_bad"\ndef fires(f):\n    print(open("/etc/passwd"))\n' \
          '    return f.__class__ is dict\n'
    problems = detector_eval.purity_problems(bad, "x_bad")
    assert any("import os" in p for p in problems)
    assert any("print" in p for p in problems) and any("open" in p for p in problems)
    assert any("__class__" in p for p in problems)
    assert detector_eval.purity_problems(DETECTOR, NAME) == []
    assert detector_eval.purity_problems(DETECTOR, "other_name") == ["NAME must be 'other_name' (the file name)"]


def test_the_eval_compares_with_the_rules_only_baseline(tmp_path):
    path = tmp_path / f"{NAME}.py"
    path.write_text(DETECTOR)
    report = detector_eval.evaluate(path, sandbox.DATA_DIR)
    assert report["detector"]["kind"] == "region_dark"
    for split in ("dev", "heldout"):
        rules, rows = report["metrics"][split]["rules_only"], report["data"][split]
        # The §13 detector raised every row of its kind: the baseline flags all of them.
        assert rules["tp"] + rules["fp"] == rows["rows"] and rules["tn"] == 0
        assert rules["tp"] == rows["positives"]
    assert {r["row_id"] for r in report["dev_rows"]} == set(author.dev_rows("region_dark"))
    assert report["data"]["heldout"]["seeds"] == [1, 2, 3]
    assert "heldout_rows" not in report  # held-out rows are aggregates only


# Sandbox, re-run and hand-off --------------------------------------------------------------------


@pytest.fixture
def box():
    b = sandbox.create("HEAD", os_sandbox=OS_SANDBOX)
    yield b
    b.remove()
    assert not b.root.exists()


def write(box: sandbox.Sandbox, guard: sandbox.AuthorGuard, detector: str = DETECTOR, test: str = TEST) -> None:
    """What Droid's Create calls do, through the same guard."""
    for path, content in ((box.detector_file(NAME), detector), (box.test_file(NAME), test)):
        assert ask(guard, create(box.repo, str(path.relative_to(box.repo)), content))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def proposal(metrics: dict, **overrides) -> author.DetectorProposal:
    values = dict(name=NAME, kind="region_dark", rationale="Raise a dark region only during an active alert.",
                  files_changed=[f"server/stormcash/detectors_proposed/{NAME}.py",
                                 f"server/tests/test_proposed_{NAME}.py"],
                  tests_passed=True, metrics=metrics, caveats=["The simulator plants an alert in every dark region."])
    return author.DetectorProposal(**(values | overrides))


def test_the_sandbox_is_a_fresh_worktree_without_secrets(box):
    assert not box.root.is_relative_to(box.repo_root)
    assert (box.repo / "server/stormcash/detectors.py").is_file()
    assert not list(box.repo.rglob(".env"))
    assert box.changed_files() == []
    script = box.droid_executable.read_text()
    assert "env -i" in script and "DATABASE_URL" not in script
    if OS_SANDBOX:
        assert "sandbox-exec" in script
        assert "(deny network*)" in box.lab_profile(show_heldout=False)
        assert "heldout" in box.lab_profile(show_heldout=False) and "heldout" not in box.lab_profile(show_heldout=True)


def test_the_rerun_accepts_true_claims_and_rejects_fabricated_metrics(deps, box):
    guard = sandbox.AuthorGuard(box.repo)
    write(box, guard)
    job = author.make_job("region_dark", ["7:8"])
    real = asyncio.run(box.run_lab("eval", NAME))
    metrics = json.loads(real["output"])["metrics"]
    verified = asyncio.run(author.verify(deps, job, box, guard, proposal(metrics)))
    assert verified["ok"], verified["checks"]
    assert [c["check"] for c in verified["checks"]] == ["files", "pure_detector", "no_secrets", "tests_rerun",
                                                       "eval_rerun", "claims_match"]

    fabricated = json.loads(json.dumps(metrics))
    fabricated["heldout"]["rules_only"]["precision"] = 0.9
    fabricated["dev"]["proposed"]["fp"] += 1
    rejected = asyncio.run(author.verify(deps, job, box, guard, proposal(fabricated)))
    assert not rejected["ok"]
    claims = next(c for c in rejected["checks"] if c["check"] == "claims_match")
    assert "metrics.heldout.rules_only.precision: Droid said 0.9" in claims["detail"]
    assert "metrics.dev.proposed.fp" in claims["detail"]

    lied = asyncio.run(author.verify(deps, job, box, guard, proposal(metrics, tests_passed=False, name="other_name")))
    claims = next(c for c in lied["checks"] if c["check"] == "claims_match")
    assert not lied["ok"] and "tests_passed" in claims["detail"] and "name" in claims["detail"]


def test_the_rerun_rejects_failing_tests_and_files_outside_the_allowlist(deps, box):
    guard = sandbox.AuthorGuard(box.repo)
    write(box, guard, test=TEST + "\n\ndef test_fails():\n    assert fires({'active_alerts': []})\n")
    metrics = json.loads(asyncio.run(box.run_lab("eval", NAME))["output"])["metrics"]
    job = author.make_job("region_dark", [])
    verified = asyncio.run(author.verify(deps, job, box, guard, proposal(metrics)))
    assert {c["check"]: c["ok"] for c in verified["checks"]}["tests_rerun"] is False
    (box.repo / "server/stormcash/detectors.py").write_text("# changed behind the guard's back\n")
    verified = asyncio.run(author.verify(deps, job, box, guard, proposal(metrics)))
    assert verified["checks"][0]["check"] == "files" and not verified["ok"]
    assert "server/stormcash/detectors.py" in verified["checks"][0]["detail"]


@pytest.mark.skipif(not OS_SANDBOX, reason="macOS sandbox-exec")
def test_droid_code_in_the_lab_has_no_network_secrets_or_held_out_data(deps, box):
    guard = sandbox.AuthorGuard(box.repo)
    probe = TEST + f'''

import socket


def test_probe():
    for target in (("1.1.1.1", 443), ("localhost", 5432)):
        try:
            socket.create_connection(target, timeout=2)
            raise AssertionError("network")
        except PermissionError:
            pass
        except OSError as exc:
            assert exc.errno == 1, exc
    for path in ({str(sandbox.DATA_DIR / "stormdesk_triage_heldout.jsonl")!r}, {str(Path.home() / ".ssh")!r} + "/x",
                 "../chalk/evals/dataset/meta_heldout.json"):
        try:
            open(path).read()
            raise AssertionError(path)
        except (PermissionError, FileNotFoundError):
            pass
    try:
        open("stormcash/detectors.py", "a").write("#")
        raise AssertionError("wrote the worktree")
    except PermissionError:
        pass
'''
    write(box, guard, test=probe)
    result = asyncio.run(box.run_lab("test", NAME))
    assert result["exit_code"] == 0, result["output"][-2000:]


class ScriptedAuthor:
    """Stands in for Droid's session: writes through the guard, runs the eval, then claims something."""

    def __init__(self, name: str = "droid", tamper=None):
        self.name, self.tamper = name, tamper

    async def run(self, job, prompt, box, guard, steps, lab_runs):
        self.prompt = prompt
        write(box, guard)
        step = steps.call("run_eval", {"name": NAME})
        assert guard.allow_lab("eval", NAME) is None
        metrics = json.loads((await box.run_lab("eval", NAME))["output"])["metrics"]
        lab_runs.append({"cmd": "eval", "name": NAME, "exit_code": 0})
        steps.result(None, True, step)
        if self.tamper:
            self.tamper(metrics)
        return author.AuthorOutcome(self.name, proposal(metrics), session_id=f"{self.name}-1",
                                    usage={"factory_credits": 1234.0}, model="claude-sonnet-5-5",
                                    model_requested="claude-sonnet-5-5",
                                    attempts=[{"attempt": 1, "ok": True, "error": None}],
                                    permission_denials=guard.denials)


def run_author(deps, runner, pr) -> tuple[dict, dict]:
    desk = author.Author(deps, runner=runner, make_sandbox=lambda: sandbox.create("HEAD", os_sandbox=OS_SANDBOX),
                         pr=pr)

    async def go():
        started = desk.start(author.make_job("region_dark", ["7:8", {"row_id": "2026:8", "note": "missed"}]),
                             check_enabled=False)
        await asyncio.gather(*desk.tasks)
        return started

    started = asyncio.run(go())
    with deps.pool.connection() as conn:
        return started, one(conn, "SELECT * FROM stormdesk_runs WHERE run_id = %s", (started["run_id"],))


def test_a_verified_droid_run_reaches_the_pr_step_once(deps, app_client):
    calls = []

    def pr(box, job, prop, run, verified):
        calls.append((prop.name, run["run_id"], run["model"], sorted(verified["files"])))
        return {"url": "https://github.com/o/r/pull/7", "number": 7, "branch": "droid/x", "label": "droid-proposal"}

    runner = ScriptedAuthor()
    started, row = run_author(deps, runner, pr)
    assert row["job"] == "author" and row["status"] == "succeeded" and row["runner"] == "droid"
    assert calls == [(NAME, started["run_id"], "claude-sonnet-5-5", [f"server/stormcash/detectors_proposed/{NAME}.py",
                                                                    f"server/tests/test_proposed_{NAME}.py"])]
    t = row["transcript"]
    assert t["pull_request"]["number"] == 7 and t["verified"]["ok"]
    assert t["usage"]["factory_credits"] == 1234.0 and t["attempts"][0]["ok"] and t["permission_denials"] == []
    assert t["sandbox"]["base_ref"] == "HEAD" and t["examples"][1] == {"row_id": "2026:8", "note": "missed"}
    assert "7:8" in runner.prompt and "heldout" not in runner.prompt
    console = app_client.get("/v1/droid/console").json()
    view = next(r for r in console["runs"] if r["run_id"] == started["run_id"])
    assert view["job"] == "author" and view["outcome"] == "valid" and view["verdict"] == f"{NAME}: PR #7 opened"
    assert view["tool_calls"] == 1 and view["subject"] == "detector for region_dark"
    assert console["builtin_calls_seen"] == {}


def test_a_fabricated_claim_never_reaches_the_pr_step(deps, app_client):
    calls = []

    def tamper(metrics):
        metrics["heldout"]["proposed"]["recall"] = 1.0
        metrics["heldout"]["proposed"]["tp"] += 5

    started, row = run_author(deps, ScriptedAuthor(tamper=tamper), lambda *a: calls.append(a))
    assert calls == []
    assert row["status"] == "invalid" and row["transcript"]["pull_request"] is None
    assert row["error"].startswith("re-run rejected the proposal: ")
    console = app_client.get("/v1/droid/console").json()
    assert next(r for r in console["runs"] if r["run_id"] == started["run_id"])["outcome"] == "rerun_rejected"
    guardrail = next(g for g in console["guardrails"] if g["key"] == "rerun_rejected")
    assert guardrail["count"] == 1


def test_a_second_request_is_refused_while_a_run_is_starting(deps):
    desk = author.Author(deps, runner=ScriptedAuthor(), pr=lambda *a: {"skipped": "test"},
                         make_sandbox=lambda: sandbox.create("HEAD", os_sandbox=OS_SANDBOX))

    async def go():
        desk.start(author.make_job("region_dark", []), check_enabled=False)
        with pytest.raises(author.AuthorError, match="already in progress"):
            desk.start(author.make_job("region_dark", []), check_enabled=False)  # before the first holds the lock
        await asyncio.gather(*desk.tasks)

    asyncio.run(go())
    with deps.pool.connection() as conn:
        assert one(conn, "SELECT count(*) AS n FROM stormdesk_runs WHERE job = 'author'")["n"] == 1


def test_a_run_that_is_not_droid_never_opens_a_pr(deps):
    calls = []
    _, row = run_author(deps, ScriptedAuthor(name="fake"), lambda *a: calls.append(a))
    assert calls == [] and row["status"] == "succeeded"
    assert "only opened for a Droid run" in row["transcript"]["pull_request"]["skipped"]


def test_the_pr_body_quotes_the_rerun_and_the_run(tmp_path):
    path = tmp_path / f"{NAME}.py"
    path.write_text(DETECTOR)
    report = detector_eval.evaluate(path, sandbox.DATA_DIR)
    body = author.pr_body(author.make_job("region_dark", []), proposal(report["metrics"]),
                          {"run_id": 42, "session_id": "s-1", "model": "claude-sonnet-5-5",
                           "model_requested": "claude-sonnet-5-5", "usage": {"factory_credits": 81234.5},
                           "tool_calls": 9, "permission_denials": [{}],
                           "sandbox": {"base_ref": "origin/main", "base_sha": "a" * 40}},
                          {"eval": report, "checks": [{"check": "claims_match", "ok": True}]})
    assert "A person decides whether to merge it" in body and "run #42" in body
    assert "81,234 Factory credits" in body and "1 permission denials" in body
    assert "| `region_dark_alert` | 1.00 | 1.00 | 5 / 0 / 0 / 4 |" in body
    assert "Generated with" not in body and "Co-Authored" not in body


# The switch and the endpoint ------------------------------------------------------------------


def test_the_switch_is_off_in_bare_settings_and_on_with_the_env(tmp_path, monkeypatch, database_url):
    assert make_settings(database_url).stormdesk_author is False
    env = tmp_path / ".env"
    env.write_text(f"DATABASE_URL={database_url}\nSERVER_SIGNING_KEY_PEM=\"{_pem()}\"\n")
    assert load_settings(env).stormdesk_author is False
    monkeypatch.setenv("STORMDESK_AUTHOR", "1")
    monkeypatch.setenv("STORMDESK_AUTHOR_MAX_CREDITS", "300000")
    settings = load_settings(env)
    assert settings.stormdesk_author and settings.stormdesk_author_max_credits == 300_000
    assert settings.stormdesk_author_base == "origin/main"


def _pem() -> str:
    from cryptography.hazmat.primitives import serialization

    from .conftest import SERVER_KEY
    return SERVER_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode().replace("\n", "\\n")


def test_the_endpoint_refuses_when_off_and_never_takes_held_out_rows(app_client):
    headers = {"X-SC-Operator": "Alex"}
    state = app_client.get("/v1/stormdesk/author-detector").json()
    assert state["enabled"] is False and "STORMDESK_AUTHOR is off" in state["reasons"] and state["runs"] == []
    resp = app_client.post("/v1/stormdesk/author-detector", json={"gap": "region_dark"}, headers=headers)
    assert resp.status_code == 409 and "STORMDESK_AUTHOR is off" in resp.json()["detail"]
    assert app_client.post("/v1/stormdesk/author-detector", json={"gap": "region_dark"}).status_code == 401
    resp = app_client.post("/v1/stormdesk/author-detector", json={"gap": "region_dark", "examples": ["1:11"]},
                           headers=headers)
    assert resp.status_code == 400 and "held-out rows are never shown" in resp.json()["detail"]
    resp = app_client.post("/v1/stormdesk/author-detector", json={"gap": "make it better"}, headers=headers)
    assert resp.status_code == 400
    resp = app_client.post("/v1/stormdesk/author-detector", json={"gap": "region_dark", "examples": ["42:1"]},
                           headers=headers)
    assert resp.status_code == 400 and "not region_dark" in resp.json()["detail"]


def test_secret_values_are_found_by_name_only():
    settings = make_settings("postgresql://u:hunter2-long-pass@db.example/x", factory_api_key="fk-1234567890")
    secrets = sandbox.secret_values(settings)
    hits = sandbox.secret_hits(["x = 'fk-1234567890'", "hunter2-long-pass"], secrets)
    assert "FACTORY_API_KEY" in hits and "DATABASE_URL password" in hits
    assert sandbox.secret_hits([DETECTOR, TEST], secrets) == []
