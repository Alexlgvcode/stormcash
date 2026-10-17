"""WS3 #38: GET /v1/evals feeds the Evals tab from chalk/evals/results (spec §18.5)."""

from __future__ import annotations

import json

from stormcash.routes import evals

RULES_ONLY = evals.DEFAULT_DIR / "20261017T023627Z-rules_only.json"


def test_the_saved_runs_fill_both_columns_from_one_dataset(app_client):
    out = app_client.get("/v1/evals").json()
    rules, droid = out["columns"]["rules_only"], out["columns"]["stormdesk"]
    assert rules is not None and droid is not None
    assert rules["runner"] == "rules_only" and droid["runner"] == "droid" and droid["complete"] is True
    # Both columns score the same dataset revision, and every dataset row is in each result.
    assert droid["chalk"]["dataset_revision_id"] == rules["chalk"]["dataset_revision_id"]
    assert droid["dataset"]["sha256"] == rules["dataset"]["sha256"]
    for run in (rules, droid):
        assert run["dataset"]["rows"] == len(run["rows"])
    assert droid["runners_seen"] == {"droid": droid["dataset"]["rows"]}
    assert droid["models_seen"] == [droid["model"]] and all(r["models_used"] == [droid["model"]] for r in droid["rows"])
    fakes = [r for r in out["other_runs"] if r["runner"] == "fake"]
    assert fakes and all("pipeline check" in r["reason"] for r in fakes)
    assert all("metrics" not in r and "rows" not in r for r in out["other_runs"])  # no numbers from them
    # Held-out runs never reach the main section; they have their own, on their own rows.
    held = out["heldout"]["columns"]["rules_only"]
    assert held["eval"] == "stormdesk-triage-heldout" and held["dataset"]["rows"] == len(held["rows"])
    assert set(held["dataset"]["seeds"]).isdisjoint(rules["dataset"]["seeds"])
    assert rules["eval"] == droid["eval"] == "stormdesk-triage"


def test_no_results_at_all(app_client, tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "DEFAULT_DIR", tmp_path / "missing")
    out = app_client.get("/v1/evals").json()
    empty = {"columns": {"rules_only": None, "stormdesk": None}, "other_runs": []}
    assert out == {**empty, "heldout": empty, "errors": [], "runs_found": 0}


def test_a_stormdesk_claim_is_checked_and_the_newest_run_wins(app_client, tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "DEFAULT_DIR", tmp_path)
    base = json.loads(RULES_ONLY.read_text())

    def save(name: str, **changes) -> None:
        (tmp_path / name).write_text(json.dumps({**base, **changes}))

    rows = base["dataset"]["rows"]
    droid = {"runner": "droid", "table_column": "stormdesk", "is_agent_result": True, "runners_seen": {"droid": rows},
             "metrics": {**base["metrics"], "fallback_from_droid": 0}, "complete": True,
             "model": "claude-sonnet-5-5", "models_seen": ["claude-sonnet-5-5"]}
    save("a-rules.json")
    save("b-rules.json", timestamp=base["timestamp"] + 60)
    save("c-mixed.json", **{**droid, "runners_seen": {"droid": 47, "fake": 1},
                            "metrics": {**base["metrics"], "fallback_from_droid": 1}}, timestamp=base["timestamp"] + 90)
    save("d-liar.json", **{**droid, "runner": "fake"}, timestamp=base["timestamp"] + 100)
    save("d2-partial.json", **{**droid, "complete": False}, timestamp=base["timestamp"] + 101)
    save("d3-two-models.json", **{**droid, "models_seen": ["claude-sonnet-5-5", "droid-core"]},
         timestamp=base["timestamp"] + 102)
    save("d4-short.json", **{**droid, "rows": base["rows"][:-1]}, timestamp=base["timestamp"] + 103)
    (tmp_path / "e-broken.json").write_text("{")
    (tmp_path / "f-other.json").write_text(json.dumps({"schema_version": 1, "eval": "something-else"}))
    out = app_client.get("/v1/evals").json()
    assert out["columns"]["rules_only"]["file"] == "b-rules.json"
    assert out["columns"]["stormdesk"] is None
    reasons = {r["file"]: r["reason"] for r in out["other_runs"]}
    assert reasons == {"a-rules.json": "an older run for this column",
                       "c-mixed.json": "some rows weren't answered by Droid",
                       "d-liar.json": "runner is 'fake', not Droid",
                       "d2-partial.json": "an incomplete run (task errors, or the Droid guard stopped it)",
                       "d3-two-models.json": "not one named model on every row (['claude-sonnet-5-5', 'droid-core'])",
                       "d4-short.json": "its rows don't match the dataset's row count"}
    assert [e["file"] for e in out["errors"]] == ["e-broken.json", "f-other.json"]

    save("g-droid.json", **droid, timestamp=base["timestamp"] + 120)
    out = app_client.get("/v1/evals").json()  # read on every request: no restart
    assert out["columns"]["stormdesk"]["file"] == "g-droid.json"


def test_heldout_rules_column_pairs_with_the_stormdesk_rows(app_client, tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "DEFAULT_DIR", tmp_path)
    base = json.loads(RULES_ONLY.read_text())
    rows = base["dataset"]["rows"]

    def save(name: str, sha: str, ts: int, **changes) -> None:
        (tmp_path / name).write_text(json.dumps({**base, "eval": "stormdesk-triage-heldout", "timestamp": ts,
                                                 "dataset": {**base["dataset"], "sha256": sha}, **changes}))

    droid = {"runner": "droid", "table_column": "stormdesk", "is_agent_result": True, "runners_seen": {"droid": rows},
             "metrics": {**base["metrics"], "fallback_from_droid": 0}, "complete": True,
             "model": "claude-sonnet-5-5", "models_seen": ["claude-sonnet-5-5"]}
    save("a-rules-seeds-1-2.json", "s12", 10)
    save("b-rules-seeds-1-2-3.json", "s123", 20)
    save("c-droid-seeds-1-2.json", "s12", 30, **droid)
    out = app_client.get("/v1/evals").json()
    assert out["columns"] == {"rules_only": None, "stormdesk": None}  # nothing held-out in the main section
    held = out["heldout"]["columns"]
    assert held["stormdesk"]["file"] == "c-droid-seeds-1-2.json"
    assert held["rules_only"]["file"] == "a-rules-seeds-1-2.json"  # the same rows, not the newest rules run
    reasons = {r["file"]: r["reason"] for r in out["heldout"]["other_runs"]}
    assert reasons == {"b-rules-seeds-1-2-3.json": "a rules-only run on other rows than the StormDesk column"}
