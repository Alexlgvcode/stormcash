"""Chalk functions for the second-opinion reviewer eval (spec §14.7b, §15.3): replay tasks and scorers.

"v2 alone" and "v2 + reviewer" are two Evaluations on one dataset revision
(stormdesk-review-<name>): the frozen prompt-v2 outputs and, per row, the
stored reply of one live review (run_review.py made them; the review endpoint
isn't idempotent, so it runs from this machine, never from a Chalk task that
could be delivered twice). Both tasks replay what a person would see; the
scorers grade where each row ends up. Self-contained: Chalk ships this file.

Routing, from `service.after_review`: v2 alone sends a row to a person when its
kind isn't "none". With the reviewer, a valid agent review that disagrees (or
finds the evidence insufficient) keeps or reopens the row for a person; every
other review leaves v2's decision. Kind and action never change.

| Scorer | Score |
|---|---|
| valid-json (built-in) | the output parses as JSON |
| routing-correct | real rows reach a person, honest rows don't |
| real-reaches-person | real rows only: it reaches a person (honest rows pass: metadata applies false) |
| no-false-alarm | honest rows only: it doesn't reach a person (real rows pass: metadata applies false) |
| review-citations-valid | reviewer eval only: the review's citations held (an invalid review is shown, not counted) |
"""

import json

import chalkcompute


def _flag(v2_output):
    flag = json.loads(v2_output)
    return {k: v for k, v in flag.items() if k != "_run"}


@chalkcompute.function(name="sd-review-v2-alone", concurrency=8)
def v2_alone(v2_output: str) -> str:
    flag = _flag(v2_output)
    return json.dumps({"variant": "v2 alone", "reaches_person": flag["kind"] != "none", "kind": flag["kind"],
                       "proposed_action": flag["proposed_action"], "agents_disagree": False, "review": None},
                      sort_keys=True)


@chalkcompute.function(name="sd-review-v2-with-reviewer", concurrency=8)
def v2_with_reviewer(v2_output: str, review_output: str) -> str:
    flag, stored = _flag(v2_output), json.loads(review_output)
    after = stored["after_review"]
    review = stored.get("output") or {}
    return json.dumps({
        "variant": "v2 + reviewer", "reaches_person": after["status"] == "open", "kind": after["kind"],
        "proposed_action": after["proposed_action"], "agents_disagree": bool(after["agents_disagree"]),
        "v2_kind": flag["kind"], "v2_action": flag["proposed_action"],
        "review": {"verdict": review.get("verdict"), "status": stored.get("status"),
                   "citations_valid": stored.get("citations_valid"), "runner": stored.get("runner"),
                   "model": stored.get("model"), "prompt_version": stored.get("prompt_version"),
                   "suggested_kind": review.get("suggested_kind"), "suggested_action": review.get("suggested_action"),
                   "evidence_ids": review.get("evidence_ids") or [], "reasons": review.get("reasons") or [],
                   "run_id": stored.get("run_id"),
                   "factory_credits": (stored.get("usage") or {}).get("factory_credits"),
                   "duration_s": stored.get("duration_s")},
    }, sort_keys=True)


def _routed(output):
    try:
        out = json.loads(output or "")
    except ValueError:
        return None
    return out if isinstance(out, dict) and isinstance(out.get("reaches_person"), bool) else None


valid_json = chalkcompute.scorers.json_valid(name="valid-json")


@chalkcompute.function(name="routing-correct", concurrency=8)
def routing_correct(output: str, honest_subject: bool) -> chalkcompute.EvaluationScorerResult:
    out = _routed(output)
    ok = out is not None and out["reaches_person"] != honest_subject
    return chalkcompute.EvaluationScorerResult(
        score=1.0 if ok else 0.0, metadata={"reaches_person": out and out["reaches_person"], "honest": honest_subject})


@chalkcompute.function(name="real-reaches-person", concurrency=8)
def real_reaches_person(output: str, honest_subject: bool) -> chalkcompute.EvaluationScorerResult:
    if honest_subject:
        return chalkcompute.EvaluationScorerResult(score=1.0, metadata={"applies": False})
    out = _routed(output)
    return chalkcompute.EvaluationScorerResult(score=1.0 if out and out["reaches_person"] else 0.0,
                                               metadata={"applies": True})


@chalkcompute.function(name="no-false-alarm", concurrency=8)
def no_false_alarm(output: str, honest_subject: bool) -> chalkcompute.EvaluationScorerResult:
    if not honest_subject:
        return chalkcompute.EvaluationScorerResult(score=1.0, metadata={"applies": False})
    out = _routed(output)
    return chalkcompute.EvaluationScorerResult(score=1.0 if out is not None and not out["reaches_person"] else 0.0,
                                               metadata={"applies": True})


@chalkcompute.function(name="review-citations-valid", concurrency=8)
def review_citations_valid(output: str) -> chalkcompute.EvaluationScorerResult:
    out = _routed(output)
    review = (out or {}).get("review") or {}
    ok = review.get("status") == "succeeded" and review.get("citations_valid") is True
    return chalkcompute.EvaluationScorerResult(score=1.0 if ok else 0.0,
                                               metadata={"status": review.get("status"), "verdict": review.get("verdict")})


V2_ALONE_SCORERS = {"valid-json": valid_json, "routing-correct": routing_correct,
                    "real-reaches-person": real_reaches_person, "no-false-alarm": no_false_alarm}
WITH_REVIEWER_SCORERS = {**V2_ALONE_SCORERS, "review-citations-valid": review_citations_valid}
