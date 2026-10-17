"""The StormDesk eval scorers (spec §15.3), deployed as Chalk functions on import.

Self-contained on purpose: Chalk ships this one file to each scorer's worker.
A row whose output isn't a Flag scores 0 on every function scorer.

| Scorer | Pass condition |
|---|---|
| valid-json (built-in) | the output parses as JSON |
| kind-correct | output.kind == label_kind |
| action-correct | output.proposed_action == label_action |
| no-false-flag | if honest_subject: kind "none", or severity "info" with action "none" (other rows pass: nothing to falsely flag) |
| citations-valid | the server's citation check (§14.7) passed. Not in the rules-only evaluation: it cites nothing (n/a) |

Every scorer returns one score per row: Chalk computes no score summary for a
run whose scorers return lists (checked on Oct 17).
"""

import json

import chalkcompute

KINDS = {"merchant_silence", "cap_drain", "region_dark", "none"}
SEVERITIES = {"info", "review", "urgent"}
ACTIONS = {"none", "lower_merchant_limit", "hold_pool_payout", "freeze_cert", "dispatch_relay"}


def parse_flag(output):
    """The Flag (§14.5) in a task output, or None if it isn't one."""
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


def dismisses(flag) -> bool:
    """The Flag raises nothing an operator would act on."""
    return flag["kind"] == "none" or (flag["severity"] == "info" and flag["proposed_action"] == "none")


valid_json = chalkcompute.scorers.json_valid(name="valid-json")


@chalkcompute.function(name="kind-correct", concurrency=8)
def kind_correct(output: str, label_kind: str) -> chalkcompute.EvaluationScorerResult:
    flag = parse_flag(output)
    got = flag["kind"] if flag else None
    return chalkcompute.EvaluationScorerResult(score=1.0 if got == label_kind else 0.0,
                                               metadata={"got": got, "want": label_kind, "flag": flag is not None})


@chalkcompute.function(name="action-correct", concurrency=8)
def action_correct(output: str, label_action: str) -> chalkcompute.EvaluationScorerResult:
    flag = parse_flag(output)
    got = flag["proposed_action"] if flag else None
    return chalkcompute.EvaluationScorerResult(score=1.0 if got == label_action else 0.0,
                                               metadata={"got": got, "want": label_action, "flag": flag is not None})


@chalkcompute.function(name="no-false-flag", concurrency=8)
def no_false_flag(output: str, honest_subject: bool) -> chalkcompute.EvaluationScorerResult:
    if not honest_subject:  # only honest subjects can be falsely flagged; results.py reports the honest-only rate
        return chalkcompute.EvaluationScorerResult(score=1.0, metadata={"applies": False})
    flag = parse_flag(output)
    ok = flag is not None and dismisses(flag)
    return chalkcompute.EvaluationScorerResult(
        score=1.0 if ok else 0.0,
        metadata={"applies": True, "kind": flag["kind"] if flag else None,
                  "severity": flag["severity"] if flag else None, "action": flag["proposed_action"] if flag else None})


@chalkcompute.function(name="citations-valid", concurrency=8)
def citations_valid(output: str) -> chalkcompute.EvaluationScorerResult:
    flag = parse_flag(output)
    if flag is None:
        return chalkcompute.EvaluationScorerResult(score=0.0, metadata={"reason": "no Flag"})
    run = flag.get("_run") or {}
    if run.get("citations_valid") is None:
        return chalkcompute.EvaluationScorerResult(score=0.0, metadata={"reason": "no server citation check"})
    missing = list(run.get("missing_citations") or [])
    return chalkcompute.EvaluationScorerResult(
        score=1.0 if run["citations_valid"] else 0.0,
        metadata={"cited": len(flag["evidence_ids"]), "missing": missing[:5], "server_run_id": run.get("run_id")})


SCORERS = {"valid-json": valid_json, "kind-correct": kind_correct, "action-correct": action_correct,
           "no-false-flag": no_false_flag, "citations-valid": citations_valid}
RULES_ONLY_SCORERS = {k: v for k, v in SCORERS.items() if k != "citations-valid"}  # it cites nothing: n/a
