"""Turn a Chalk Evaluation run's result rows into a results file (spec §15.3, §18.5).

Every number comes from the run's own result dataset: the task output of each
row plus the scores Chalk wrote. Nothing is typed in by hand. The runner is
read from the outputs themselves (`_run.runner`, set by the server or the
rules-only task), never from configuration, so a fake-runner or fallback run
can't be passed off as StormDesk:

- `rules_only`: the §13 baseline. `table_column: "rules_only"`.
- `droid`: every row answered by Droid with no fallback, and every row's Droid session
  used one and the same model (the one asked for), read from the session files.
  `table_column: "stormdesk"`.
- `fake` or `mixed`: saved for the record, `table_column: null`, never shown as StormDesk.
- A run with task errors (e.g. rows the gateway's breaker refused) is `complete: false`, `table_column: null`.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone

SCORERS = ("valid-json", "kind-correct", "action-correct", "no-false-flag", "citations-valid")
KINDS = {"merchant_silence", "cap_drain", "region_dark", "none"}
SEVERITIES = {"info", "review", "urgent"}
ACTIONS = {"none", "lower_merchant_limit", "hold_pool_payout", "freeze_cert", "dispatch_relay"}
SOFT_KINDS = ("merchant_silence", "cap_drain", "region_dark")
LABELS = {
    "rules_only": "Rules-only baseline",
    "fake": "Fake runner (the rules-only logic run through the server; not an agent)",
    "mixed": "Mixed runners (not a StormDesk result)",
}


def parse_flag(output):
    """Same check as eval_scorers.parse_flag (that file ships to Chalk on its own)."""
    try:
        flag = json.loads(output or "")
    except ValueError:
        return None
    if not isinstance(flag, dict):
        return None
    if flag.get("kind") not in KINDS or flag.get("severity") not in SEVERITIES or \
            flag.get("proposed_action") not in ACTIONS:
        return None
    if not isinstance(flag.get("subject_id"), str) or not isinstance(flag.get("evidence_ids"), list) or \
            not isinstance(flag.get("exposure_cents"), int) or not isinstance(flag.get("summary"), str):
        return None
    return flag


def dismisses(flag: dict) -> bool:
    return flag["kind"] == "none" or (flag["severity"] == "info" and flag["proposed_action"] == "none")


def rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def row_runner(row: dict, flag: dict | None) -> str | None:
    if flag is not None:
        return (flag.get("_run") or {}).get("runner")
    found = re.search(r"\(runner (\w+),", row.get("output") or "")  # gateway.to_output's no-Flag text
    return found.group(1) if found else None


def runner_of(runners: Counter, fallbacks: int, droid_models: list | None = None) -> str:
    """`droid_models`: each Droid row's (models_used, model asked for); all must be the same single model."""
    kinds = set(runners)
    if kinds == {"rules_only"}:
        return "rules_only"
    if kinds == {"droid"} and not fallbacks:
        used = {tuple(u or ()) for u, _ in droid_models or []}
        asked = {a for _, a in droid_models or []}
        if len(used) == 1 and len(next(iter(used))) == 1 and (asked == {None} or asked == {next(iter(used))[0]}):
            return "droid"
        return "mixed"
    if kinds == {"fake"}:
        return "fake"
    return "mixed"


def _score(row: dict, name: str) -> float | None:
    """A row's score; a scorer that returned a list may store a list (empty = no score)."""
    value = row.get(f"{name}_value")
    if isinstance(value, list):
        value = sum(value) / len(value) if value else None
    if value is None or value != value:  # None or NaN
        return None
    return float(value)


def summarize(rows: list[dict], *, chalk: dict, dataset: dict, mode: str, git_sha: str | None,
              now: int, scorers: list[str] = SCORERS, droid_audit: dict | None = None) -> dict:
    """The results file for one run. `rows` are the result dataset's rows (dicts); `scorers` are the
    evaluation's scorers (the rules-only evaluation has no citations-valid: it cites nothing)."""
    parsed = []
    for row in rows:
        flag = None if row.get("output_error") else parse_flag(row.get("output"))
        parsed.append((row, flag))

    runners = Counter(r for r in (row_runner(row, flag) for row, flag in parsed) if r)
    fallbacks = sum(1 for _, flag in parsed if flag and (flag.get("_run") or {}).get("fallback_from_droid"))
    droid_runs = [(f.get("_run") or {}) for _, f in parsed if f and (f.get("_run") or {}).get("runner") == "droid"]
    runner = runner_of(runners, fallbacks, [(r.get("models_used"), r.get("model")) for r in droid_runs])
    models = sorted({m for r in droid_runs for m in (r.get("models_used") or [])})
    model = models[0] if len(models) == 1 else (", ".join(models) or None)
    audit_models = ((droid_audit or {}).get("audit") or {}).get("models_seen")
    if runner == "droid" and audit_models is not None and audit_models != models:
        runner = "mixed"  # some session (e.g. a retried attempt) used another model
    task_errors = sum(1 for r, _ in parsed if r.get("output_error"))
    complete = task_errors == 0 and not (droid_audit or {}).get("tripped")
    label = f"StormDesk (Droid{', ' + model if model else ''})" if runner == "droid" else LABELS[runner]

    def caught(row, flag) -> bool:
        return flag is not None and flag["kind"] == row["label_kind"] and flag["proposed_action"] == row["label_action"]

    def flagged(flag) -> bool:
        return flag is not None and not dismisses(flag)

    def pool_cents(row) -> int:
        return int(json.loads(row["features"]).get("pool_funded_cents") or 0) if row["kind"] == "merchant_silence" else 0

    real = [(r, f) for r, f in parsed if not r["honest_subject"]]
    honest = [(r, f) for r, f in parsed if r["honest_subject"]]
    colluders = [(r, f) for r, f in real if r["label_scenario"] == "colluder"]

    precision = {}
    for kind in SOFT_KINDS:
        raised = [(r, f) for r, f in parsed if flagged(f) and f["kind"] == kind]
        right = sum(1 for r, _ in raised if r["label_kind"] == kind)
        precision[kind] = {"flagged": len(raised), "correct": right, "precision": rate(right, len(raised))}

    checked = [f["_run"]["citations_valid"] for _, f in parsed
               if f and (f.get("_run") or {}).get("citations_valid") is not None]
    metrics = {
        "real_caught": {"caught": sum(caught(r, f) for r, f in real), "total": len(real),
                        "recall": rate(sum(caught(r, f) for r, f in real), len(real))},
        "colluders_caught": {"caught": sum(caught(r, f) for r, f in colluders), "total": len(colluders),
                             "recall": rate(sum(caught(r, f) for r, f in colluders), len(colluders))},
        "honest_flagged": {"flagged": sum(flagged(f) for _, f in honest), "total": len(honest),
                           "false_flag_rate": rate(sum(flagged(f) for _, f in honest), len(honest))},
        "precision_by_kind": precision,
        "citations_valid": ({"valid": sum(checked), "checked": len(checked), "rate": rate(sum(checked), len(checked))}
                            if checked else None),
        "pool_cents": {
            "note": "pool money in each merchant_silence candidate's 6 h window (its frozen features)",
            "at_colluders": sum(pool_cents(r) for r, _ in colluders),
            "held_correctly": sum(pool_cents(r) for r, f in colluders
                                  if f and f["proposed_action"] == "hold_pool_payout"),
            "held_from_honest_shops": sum(pool_cents(r) for r, f in honest
                                          if f and f["proposed_action"] == "hold_pool_payout"),
        },
        "factory_credits": {
            "note": "Factory credits of each row's Droid session (the attempt that answered); droid_audit counts every session",
            "rows_total": sum((r.get("factory_credits") or 0) for r in droid_runs) if droid_runs else None,
            "rows_with_usage": sum(1 for r in droid_runs if r.get("factory_credits") is not None),
        },
        "rows_without_flag": sum(1 for _, f in parsed if f is None),
        "task_errors": task_errors,
        "fallback_from_droid": fallbacks,
    }

    scores = {}
    for name in SCORERS:
        values = [v for r, _ in parsed if (v := _score(r, name)) is not None]
        scores[name] = {"in_evaluation": name in scorers, "mean": round(sum(values) / len(values), 4) if values else None,
                        "scored_rows": len(values), "errors": sum(1 for r, _ in parsed if r.get(f"{name}_error"))}
    # no-false-flag passes non-honest rows (nothing to falsely flag); this is its mean over honest rows only.
    honest_values = [v for r, _ in honest if (v := _score(r, "no-false-flag")) is not None]
    scores["no-false-flag"]["mean_honest_rows"] = rate(sum(honest_values), len(honest_values)) \
        if honest_values else None

    scenarios: dict[str, list] = {}
    for row, flag in parsed:
        scenarios.setdefault(row["label_scenario"], []).append((row, flag))
    per_scenario = []
    for scenario, items in sorted(scenarios.items()):
        first = items[0][0]
        per_scenario.append({
            "scenario": scenario,
            "rows": len(items),
            "honest": first["honest_subject"],
            "label_kind": first["label_kind"],
            "label_action": first["label_action"],
            "caught": None if first["honest_subject"] else sum(caught(r, f) for r, f in items),
            "dismissed": sum(1 for _, f in items if f is not None and dismisses(f)) if first["honest_subject"] else None,
            "flagged": sum(flagged(f) for _, f in items),
            "kind_correct": sum(1 for r, _ in items if _score(r, "kind-correct") == 1.0),
            "action_correct": sum(1 for r, _ in items if _score(r, "action-correct") == 1.0),
            "without_flag": sum(1 for _, f in items if f is None),
        })

    out_rows = []
    for row, flag in parsed:
        run = (flag or {}).get("_run") or {}
        out_rows.append({
            "row_id": row["row_id"], "seed": row["seed"], "candidate_id": row["candidate_id"], "kind": row["kind"],
            "subject_id": row["subject_id"], "subject_name": row["subject_name"],
            "label_scenario": row["label_scenario"], "label_kind": row["label_kind"],
            "label_action": row["label_action"], "honest_subject": row["honest_subject"],
            "output_kind": flag["kind"] if flag else None,
            "output_severity": flag["severity"] if flag else None,
            "output_action": flag["proposed_action"] if flag else None,
            "summary": flag["summary"] if flag else None,
            "reasoning": flag.get("reasoning") if flag else None,
            "evidence_ids": flag["evidence_ids"] if flag else [],
            "exposure_cents": flag["exposure_cents"] if flag else None,
            "runner": row_runner(row, flag), "server_run_id": run.get("run_id"),
            "models_used": run.get("models_used"), "factory_credits": run.get("factory_credits"),
            "citations_valid": run.get("citations_valid"),
            "error": row.get("output_error") or (None if flag else (row.get("output") or "")[:300]),
            "scores": {name: _score(row, name) for name in SCORERS},
        })

    return {
        "schema_version": 1,
        "eval": "stormdesk-triage",
        "runner": runner,
        "runner_label": label,
        "is_agent_result": runner == "droid",
        "complete": complete,
        "table_column": {"rules_only": "rules_only", "droid": "stormdesk"}.get(runner) if complete else None,
        "model": model,
        "mode": mode,
        "timestamp": now,
        "timestamp_iso": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": git_sha,
        "chalk": chalk,
        "dataset": dataset,
        "runners_seen": dict(runners),
        "models_seen": models,
        "droid_audit": droid_audit,
        "scorers": scores,
        "metrics": metrics,
        "per_scenario": per_scenario,
        "rows": out_rows,
    }
