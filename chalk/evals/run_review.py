"""The second-opinion reviewer eval (spec §14.7b, §15.3): "v2 alone" vs "v2 + reviewer" on frozen outputs.

    server/.venv/bin/python chalk/evals/stack.py up --runner droid --model claude-sonnet-5-5 \\
        --max-credits 1350000 --seeds 1 2 --no-tunnel
    cd chalk && uv run python evals/run_review.py review --name heldout-v2 --max-credits 1350000 --limit 1
    cd chalk && uv run python evals/run_review.py review --name heldout-v2 --max-credits 1350000
    cd chalk && uv run python evals/run_review.py score --name heldout-v2

`review` sends each row of dataset/stormdesk_review_<name>.jsonl (made by
build_review_dataset.py) to its seed's server: `POST /v1/stormdesk/review`
with the row's frozen prompt-v2 Flag. One row at a time, from this machine:
the endpoint isn't idempotent, so a row is written to the progress file
(.state/review_<name>.jsonl) before it is sent and is never sent again. It stops
at the first reply that wasn't Droid on the stack's model with reviewer prompt
v1 (or that fell back), and before any row that wouldn't fit under
--max-credits at 1.25 x the average review so far.

`score` needs every row reviewed by those rules. It uploads the rows with both
outputs and runs two Chalk Evaluations on that one revision (review_eval.py):
the v2 proposal alone, and the proposal after the review. Results go to
results/review/<timestamp>-review-<name>.json, outside the Evals tab's triage
columns.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import gateway
from run_eval import EVALS, STATE, SUITE, git_sha, upload

RESULTS = EVALS / "results" / "review"
REVIEW_PROMPT_VERSION = 1
ROW_ESTIMATE = 65000.0  # credits per review assumed until one is done (live tests took 16,828 and 56,198)
MARGIN = 1.25
OPERATOR = "eval"


def dataset_rows(name: str) -> tuple[list[dict], dict]:
    slug = name.replace("-", "_")
    rows = [json.loads(line) for line in (EVALS / "dataset" / f"stormdesk_review_{slug}.jsonl").read_text().splitlines()]
    return rows, json.loads((EVALS / "dataset" / f"meta_review_{slug}.json").read_text())


def progress_file(name: str) -> Path:
    return STATE / f"review_{name.replace('-', '_')}.jsonl"


def load_progress(name: str) -> tuple[set[str], dict[str, dict]]:
    """(rows sent, replies by row_id)."""
    sent, replies = set(), {}
    path = progress_file(name)
    for line in path.read_text().splitlines() if path.exists() else []:
        event = json.loads(line)
        if event["event"] == "sent":
            sent.add(event["row_id"])
        elif event["event"] == "reply":
            replies[event["row_id"]] = event["response"]
    return sent, replies


def record(name: str, event: dict) -> None:
    STATE.mkdir(exist_ok=True)
    with progress_file(name).open("a") as f:
        f.write(json.dumps({**event, "at": int(time.time())}) + "\n")


def guard(reply: dict, model: str, session: dict | None) -> str | None:
    """Why this reply breaks the eval's rules, or None."""
    if reply.get("runner") != "droid":
        return f"answered by {reply.get('runner')!r}, not Droid"
    if reply.get("fallback_from_droid"):
        return f"fell back from Droid: {reply['fallback_from_droid']}"
    if reply.get("model") != model:
        return f"the server says it ran {reply.get('model')!r}, not {model}"
    if reply.get("prompt_version") != REVIEW_PROMPT_VERSION:
        return f"reviewer prompt_version {reply.get('prompt_version')}, not {REVIEW_PROMPT_VERSION}"
    if session is None or session["models_used"] != [model]:
        return f"its Droid session used {session and session['models_used']}, not only {model}"
    return None


def credits(reply: dict) -> float:
    return float((reply.get("usage") or {}).get("factory_credits") or 0)


def review(args) -> None:
    rows, _ = dataset_rows(args.name)
    stack = json.loads((STATE / "stack.json").read_text())
    if stack["runner"] != "droid" or not stack.get("model"):
        raise SystemExit("start the stack with --runner droid --model ...")
    sent, replies = load_progress(args.name)
    lost = sorted(sent - set(replies))
    if lost:
        raise SystemExit(f"rows {lost} were sent but have no reply: they are never sent again "
                         "(look for job='review' in stormdesk_runs of that seed's database)")
    for row_id, reply in replies.items():
        if reason := guard(reply, stack["model"], gateway.find_session(reply.get("session_id"))):
            raise SystemExit(f"row {row_id} broke the rules ({reason}): the eval stops here")
    todo = [r for r in rows if r["row_id"] not in sent][: args.limit]
    for row in todo:
        done = [credits(r) for r in replies.values()]
        spent = sum(done)
        per_row = MARGIN * spent / len(done) if done else ROW_ESTIMATE
        if spent + per_row > args.max_credits:
            raise SystemExit(f"stopping before {row['row_id']}: {spent:.0f} spent + {per_row:.0f} > {args.max_credits:.0f}")
        server = stack["servers"][str(row["seed"])]
        record(args.name, {"event": "sent", "row_id": row["row_id"]})  # written first: never send a row twice
        req = urllib.request.Request(
            f"{server}/v1/stormdesk/review", method="POST",
            data=json.dumps({"candidate_id": row["candidate_id"], "proposal": json.loads(row["v2_output"])}).encode(),
            headers={"Content-Type": "application/json", "X-SC-Operator": OPERATOR})
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                reply = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            record(args.name, {"event": "error", "row_id": row["row_id"], "status": exc.code,
                               "error": exc.read()[:300].decode(errors="replace")})
            raise SystemExit(f"row {row['row_id']}: the server answered {exc.code}; the eval stops here")
        record(args.name, {"event": "reply", "row_id": row["row_id"], "response": reply})
        replies[row["row_id"]] = reply
        session = gateway.find_session(reply.get("session_id"))
        verdict = (reply.get("output") or {}).get("verdict")
        print(f"{row['row_id']}: {reply.get('status')} {verdict} -> {reply.get('after_review')} "
              f"{credits(reply):.0f} credits, {reply.get('duration_s')} s", flush=True)
        if reason := guard(reply, stack["model"], session):
            raise SystemExit(f"row {row['row_id']} broke the rules ({reason}): the eval stops here")
    print(f"{len(replies)}/{len(rows)} rows reviewed, {sum(credits(r) for r in replies.values()):.0f} credits")


# Scoring ---------------------------------------------------------------------------------------

def routed(output: str | None) -> dict | None:
    try:
        out = json.loads(output or "")
    except ValueError:
        return None
    return out if isinstance(out, dict) and isinstance(out.get("reaches_person"), bool) else None


def summarize(v2_rows: list[dict], reviewed_rows: list[dict], replies: dict[str, dict], *, model: str,
              chalk: dict, dataset: dict, now: int) -> dict:
    """Where every row ends up without and with the reviewer, from the two runs' result rows."""
    def variant(rows: list[dict]) -> dict:
        outs = [(r, routed(r.get("output"))) for r in rows]
        real = [(r, o) for r, o in outs if not r["honest_subject"]]
        honest = [(r, o) for r, o in outs if r["honest_subject"]]
        right = sum(1 for r, o in outs if o and o["kind"] == r["label_kind"] and o["proposed_action"] == r["label_action"])
        scorer_names = sorted({k[:-6] for r in rows for k in r if k.endswith("_value")})
        return {
            "real_reach_a_person": {"n": sum(1 for _, o in real if o and o["reaches_person"]), "of": len(real)},
            "honest_reach_a_person": {"n": sum(1 for _, o in honest if o and o["reaches_person"]), "of": len(honest)},
            "kind_and_action_correct": {"n": right, "of": len(outs)},
            "task_errors": sum(1 for r, o in outs if o is None),
            "scorers": {s: round(sum(r[f"{s}_value"] for r in rows) / len(rows), 4) for s in scorer_names},
        }

    by_row = {r["row_id"]: r for r in reviewed_rows}
    per_row, verdicts, statuses = [], Counter(), Counter()
    for r in sorted(v2_rows, key=lambda r: (r["seed"], r["candidate_id"])):
        alone, after = routed(r.get("output")), routed(by_row[r["row_id"]].get("output"))
        reply = replies[r["row_id"]]
        review = (after or {}).get("review") or {}
        v2_right = bool(alone) and alone["kind"] == r["label_kind"] and alone["proposed_action"] == r["label_action"]
        verdicts[review.get("verdict")] += 1
        statuses[review.get("status")] += 1
        per_row.append({
            "row_id": r["row_id"], "subject_name": r["subject_name"], "label_scenario": r["label_scenario"],
            "honest_subject": r["honest_subject"], "label_kind": r["label_kind"], "label_action": r["label_action"],
            "v2_kind": alone and alone["kind"], "v2_action": alone and alone["proposed_action"], "v2_right": v2_right,
            "v2_reaches_person": alone and alone["reaches_person"],
            "verdict": review.get("verdict"), "review_status": review.get("status"),
            "agents_disagree": bool(after and after["agents_disagree"]),
            "reaches_person_after_review": after and after["reaches_person"],
            "suggested_kind": review.get("suggested_kind"), "suggested_action": review.get("suggested_action"),
            "reasons": review.get("reasons"), "review_run_id": reply.get("run_id"),
            "factory_credits": credits(reply), "duration_s": reply.get("duration_s"),
        })
    esc = [p for p in per_row if p["agents_disagree"]]
    sessions = [gateway.find_session(rep.get("session_id")) for rep in replies.values()]
    guard_breaks = {rid: reason for rid, rep in replies.items()
                    if (reason := guard(rep, model, gateway.find_session(rep.get("session_id"))))}
    complete = len(replies) == len(v2_rows) and not guard_breaks
    durations = [p["duration_s"] for p in per_row if p["duration_s"] is not None]
    return {
        "schema_version": 1,
        "eval": "stormdesk-review",
        "complete": complete,
        "model": model,
        "reviewer_prompt_version": REVIEW_PROMPT_VERSION,
        "timestamp": now,
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "git_sha": git_sha(),
        "chalk": chalk,
        "dataset": dataset,
        "routing_rule": "v2 alone: a row reaches a person when its kind isn't 'none'. v2 + reviewer: "
                        "service.after_review (a valid agent review that disagrees or finds the evidence "
                        "insufficient keeps or reopens it; anything else leaves v2's decision). Kind and action "
                        "never change.",
        "v2_alone": variant(v2_rows),
        "v2_with_reviewer": variant(reviewed_rows),
        "reviewer": {
            "verdicts": dict(verdicts), "review_statuses": dict(statuses),
            "escalated": len(esc),
            "escalated_where_v2_was_wrong": sum(1 for p in esc if not p["v2_right"]),
            "escalated_where_v2_was_right": sum(1 for p in esc if p["v2_right"]),
            "real_cases_v2_dismissed_now_seen": sum(1 for p in esc if not p["honest_subject"] and not p["v2_reaches_person"]),
            "honest_dismissals_reopened": sum(1 for p in esc if p["honest_subject"] and not p["v2_reaches_person"]),
            "agreed_with_a_wrong_v2": sum(1 for p in per_row if p["verdict"] == "agree"
                                          and p["review_status"] == "succeeded" and not p["v2_right"]),
            "suggestion_matches_label_when_escalated": sum(
                1 for p in esc if p["suggested_kind"] == p["label_kind"] and p["suggested_action"] == p["label_action"]),
            "invalid_reviews_shown": sum(1 for p in per_row if p["review_status"] == "invalid"),
            "factory_credits": sum(p["factory_credits"] for p in per_row),
            "duration_s": {"mean": round(sum(durations) / len(durations), 1) if durations else None,
                           "max": max(durations) if durations else None},
            "runners_seen": dict(Counter(rep.get("runner") for rep in replies.values())),
            "models_seen": sorted({rep.get("model") for rep in replies.values()}),
            "session_models_seen": sorted({m for s in sessions if s for m in s["models_used"]}),
            "prompt_versions_seen": sorted({rep.get("prompt_version") for rep in replies.values()}),
            "guard_breaks": guard_breaks,
        },
        "rows": per_row,
    }


def score(args) -> None:
    import chalkcompute

    import review_eval

    rows, meta = dataset_rows(args.name)
    _, replies = load_progress(args.name)
    stack = json.loads((STATE / "stack.json").read_text()) if (STATE / "stack.json").exists() else {}
    model = args.model or stack.get("model")
    missing = [r["row_id"] for r in rows if r["row_id"] not in replies]
    if missing:
        raise SystemExit(f"rows {missing} have no review yet: only a complete set is scored")
    upload_rows = [{**{k: v for k, v in r.items() if k not in ("v2_session_id",)},
                    "review_output": json.dumps(replies[r["row_id"]], sort_keys=True)} for r in rows]
    raw = "".join(json.dumps(r, sort_keys=True) + "\n" for r in upload_rows)
    import hashlib
    sha = hashlib.sha256(raw.encode()).hexdigest()
    ref = upload(meta["name"], upload_rows, sha)
    suite = next((s for s in chalkcompute.EvaluationSuite.list_all() if s.name == SUITE), None) \
        or chalkcompute.EvaluationSuite.create(SUITE)
    runs = {}
    for key, title, task, scorers in (
            ("v2_alone", "v2 alone", review_eval.v2_alone, review_eval.V2_ALONE_SCORERS),
            ("v2_with_reviewer", "v2 + reviewer", review_eval.v2_with_reviewer, review_eval.WITH_REVIEWER_SCORERS)):
        evaluation = chalkcompute.Evaluation.create(
            f"StormDesk reviewer eval: {title} · {args.name}", dataset=ref, task=task, scorers=list(scorers.values()),
            suite_id=suite.id, metadata={"spec": "§14.7b", "variant": key, "dataset_sha256": sha,
                                         "source_run_id": meta["source_run_id"], "scorers": list(scorers)})
        run = evaluation.run(metadata={"git_sha": git_sha() or ""}).wait(timeout=1800, raise_on_failure=False)
        print(f"{title}: evaluation {evaluation.id}, run {run.id}: {run.status.name}", flush=True)
        if run.status != chalkcompute.EvaluationRunStatus.SUCCEEDED or run.result_dataset is None:
            raise SystemExit(f"run {run.id} ended {run.status.name}: {run.error_message} (no results saved)")
        runs[key] = (evaluation, run, chalkcompute.DatasetClient().read(run.result_dataset).to_pylist())
    now = int(time.time())
    summary = summarize(
        runs["v2_alone"][2], runs["v2_with_reviewer"][2], replies, model=model, now=now,
        chalk={key: {"evaluation_id": e.id, "evaluation_name": e.name, "run_id": r.id, "status": r.status.name,
                     "dataset_revision_id": e.dataset_revision_id} for key, (e, r, _) in runs.items()},
        dataset={**{k: meta[k] for k in ("name", "rows", "honest_rows", "seeds", "source_run_id",
                                         "prompt_versions", "models")}, "sha256": sha},
    )
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}-review-{args.name}" \
                     f"{'' if summary['complete'] else '-incomplete'}.json"
    path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("complete", "v2_alone", "v2_with_reviewer")}, indent=2))
    print(json.dumps({k: v for k, v in summary["reviewer"].items() if k != "guard_breaks"}, indent=2))
    print(f"wrote {path.relative_to(EVALS.parent)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p_review = sub.add_parser("review")
    p_review.add_argument("--name", required=True)
    p_review.add_argument("--max-credits", type=float, required=True)
    p_review.add_argument("--limit", type=int, default=None, help="review at most this many more rows")
    p_score = sub.add_parser("score")
    p_score.add_argument("--name", required=True)
    p_score.add_argument("--model", default=None, help="default: the eval stack's model")
    args = ap.parse_args()
    {"review": review, "score": score}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
