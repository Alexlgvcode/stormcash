"""WS3 #38: GET /v1/evals feeds the Evals tab from chalk/evals/results (spec §18.5)."""

from __future__ import annotations

import json

from stormcash.routes import evals

RULES_ONLY = evals.DEFAULT_DIR / "20261017T023627Z-rules_only.json"


def test_the_saved_runs_fill_only_the_rules_only_column(app_client):
    out = app_client.get("/v1/evals").json()
    rules = out["columns"]["rules_only"]
    assert rules["runner"] == "rules_only" and rules["dataset"]["rows"] == len(rules["rows"]) == 48
    assert rules["chalk"]["run_id"] == "85ec3bf0-3cf2-4cd9-bde2-0fb2b0d38326"
    # Until a real Droid run lands, the StormDesk column stays empty; fake runs are pipeline checks.
    assert out["columns"]["stormdesk"] is None
    fakes = [r for r in out["other_runs"] if r["runner"] == "fake"]
    assert len(fakes) == 2 and all("pipeline check" in r["reason"] for r in fakes)
    assert all("metrics" not in r and "rows" not in r for r in out["other_runs"])  # no numbers from them


def test_no_results_at_all(app_client, tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "DEFAULT_DIR", tmp_path / "missing")
    out = app_client.get("/v1/evals").json()
    assert out == {"columns": {"rules_only": None, "stormdesk": None}, "other_runs": [], "errors": [],
                   "runs_found": 0}


def test_a_stormdesk_claim_is_checked_and_the_newest_run_wins(app_client, tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "DEFAULT_DIR", tmp_path)
    base = json.loads(RULES_ONLY.read_text())

    def save(name: str, **changes) -> None:
        (tmp_path / name).write_text(json.dumps({**base, **changes}))

    droid = {"runner": "droid", "table_column": "stormdesk", "is_agent_result": True, "runners_seen": {"droid": 48},
             "metrics": {**base["metrics"], "fallback_from_droid": 0}}
    save("a-rules.json")
    save("b-rules.json", timestamp=base["timestamp"] + 60)
    save("c-mixed.json", **{**droid, "runners_seen": {"droid": 47, "fake": 1},
                            "metrics": {**base["metrics"], "fallback_from_droid": 1}}, timestamp=base["timestamp"] + 90)
    save("d-liar.json", **{**droid, "runner": "fake"}, timestamp=base["timestamp"] + 100)
    (tmp_path / "e-broken.json").write_text("{")
    (tmp_path / "f-other.json").write_text(json.dumps({"schema_version": 1, "eval": "something-else"}))
    out = app_client.get("/v1/evals").json()
    assert out["columns"]["rules_only"]["file"] == "b-rules.json"
    assert out["columns"]["stormdesk"] is None
    reasons = {r["file"]: r["reason"] for r in out["other_runs"]}
    assert reasons == {"a-rules.json": "an older run for this column",
                       "c-mixed.json": "some rows weren't answered by Droid",
                       "d-liar.json": "runner is 'fake', not Droid"}
    assert [e["file"] for e in out["errors"]] == ["e-broken.json", "f-other.json"]

    save("g-droid.json", **droid, timestamp=base["timestamp"] + 120)
    out = app_client.get("/v1/evals").json()  # read on every request: no restart
    assert out["columns"]["stormdesk"]["file"] == "g-droid.json"
