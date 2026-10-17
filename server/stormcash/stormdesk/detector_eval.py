"""Evaluate a proposed detector on the simulator's labelled candidates (spec §14.7d).

Deterministic and offline. A proposed detector is a pure Python module in
`server/stormcash/detectors_proposed/<name>.py`:

    KIND = "region_dark"      # the candidate kind it judges (§13)
    NAME = "<name>"           # its file name
    def fires(features: dict) -> bool: ...

It sees one candidate's frozen feature snapshot, the same dict the §13
detector stored, and says whether to raise it. It never acts.

The labelled rows are the Chalk eval datasets (§15.3), built from the
simulator's seeds and `labels.json`, never the live database:

- dev: `stormdesk_triage.jsonl` (seeds 42, 7, 13, 99, 2026). Droid may read it.
- held-out: `stormdesk_triage_heldout.jsonl` (seeds 1, 2, 3). Droid never reads
  it; it gets only this script's aggregate counts.

A row is positive when its label is this kind. The rules-only baseline for a
kind is the §13 detector alone: it raised every row of that kind, so it fires on
all of them. Labelled subjects of this kind that no detector raised
(`detector_misses` in the dataset's meta file) count as missed by both, since a
detector that judges candidates never sees them.

Before anything runs, the module must pass `purity_problems`: a pure function
over its features, with no I/O, no imports beyond a few stdlib math modules,
no dunder access and no printing, so it can't read the labels, reach the
network or change this script. The author job's run_eval runs this in an OS sandbox
without network either way.

    python -m stormcash.stormdesk.detector_eval --detector PATH --data DIR
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import re
import sys
from pathlib import Path

EVALUATOR = "stormcash.stormdesk.detector_eval v1"
SPLITS = {"dev": ("stormdesk_triage.jsonl", "meta.json"),
          "heldout": ("stormdesk_triage_heldout.jsonl", "meta_heldout.json")}
KINDS = ("merchant_silence", "cap_drain", "region_dark")
NAME_RE = re.compile(r"[a-z][a-z0-9_]{2,40}")

ALLOWED_IMPORTS = frozenset({"__future__", "math", "statistics", "typing", "dataclasses", "collections",
                             "collections.abc"})
FORBIDDEN_NAMES = frozenset({"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr",
                             "setattr", "delattr", "input", "print", "breakpoint", "help", "exit", "quit", "memoryview",
                             "__builtins__", "__loader__", "__spec__", "__file__"})


class EvalError(ValueError):
    """The detector can't be evaluated (not pure, wrong shape, raised on a row)."""


def purity_problems(source: str, name: str) -> list[str]:
    """Why this module isn't a pure detector named `name` ([] when it is)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax error at line {exc.lineno}: {exc.msg}"]
    problems: list[str] = []
    for node in ast.walk(tree):
        where = f"line {getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Import):
            problems += [f"{where}: import {a.name} is not allowed" for a in node.names if a.name not in ALLOWED_IMPORTS]
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in ALLOWED_IMPORTS:
                problems.append(f"{where}: from {'.' * node.level}{node.module or ''} import is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"{where}: {node.id} is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            problems.append(f"{where}: attribute {node.attr} is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append(f"{where}: global state is not allowed")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)):
            problems.append(f"{where}: fires() must be a plain function")
    top = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    for const in ("KIND", "NAME"):
        if not isinstance(top.get(const), ast.Constant) or not isinstance(top[const].value, str):
            problems.append(f"{const} must be a string literal")
    if isinstance(top.get("KIND"), ast.Constant) and top["KIND"].value not in KINDS:
        problems.append(f"KIND must be one of {', '.join(KINDS)}")
    if isinstance(top.get("NAME"), ast.Constant) and top["NAME"].value != name:
        problems.append(f"NAME must be {name!r} (the file name)")
    fires = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fires"]
    if not fires or len(fires[0].args.args) != 1:
        problems.append("fires(features) must be defined with one argument")
    return problems


def load_detector(path: Path):
    """Import a detector module from its file after the purity check."""
    path = Path(path)
    name = path.stem
    if not NAME_RE.fullmatch(name):
        raise EvalError(f"detector file name {name!r} must match {NAME_RE.pattern}")
    source = path.read_text()
    problems = purity_problems(source, name)
    if problems:
        raise EvalError("not a pure detector: " + "; ".join(problems))
    spec = importlib.util.spec_from_file_location(f"proposed_detector_{name}", path)
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    return module, hashlib.sha256(source.encode()).hexdigest()


def _rows(data_dir: Path, split: str) -> tuple[list[dict], dict, str]:
    rows_file, meta_file = SPLITS[split]
    raw = (data_dir / rows_file).read_bytes()
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    for r in rows:  # the dataset keeps each snapshot as a JSON string (Chalk columns are flat)
        if isinstance(r["features"], str):
            r["features"] = json.loads(r["features"])
    meta = json.loads((data_dir / meta_file).read_text())
    return rows, meta, hashlib.sha256(raw).hexdigest()


def _counts(decisions: list[tuple[bool, bool]], missed: int) -> dict:
    """(fired, positive) per row, plus positives no candidate raised."""
    tp = sum(1 for f, p in decisions if f and p)
    fp = sum(1 for f, p in decisions if f and not p)
    fn = sum(1 for f, p in decisions if not f and p) + missed
    tn = sum(1 for f, p in decisions if not f and not p)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None}


def _fires(module, features: dict, where: str) -> bool:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            result = module.fires(copy.deepcopy(features))
    except Exception as exc:
        raise EvalError(f"fires() raised {type(exc).__name__} on {where}") from None
    if not isinstance(result, bool):
        raise EvalError(f"fires() returned {type(result).__name__}, not bool, on {where}")
    return result


def evaluate(detector: Path, data_dir: Path) -> dict:
    """The proposed detector next to the rules-only baseline, on dev and held-out rows."""
    module, digest = load_detector(detector)
    kind, name = module.KIND, module.NAME
    report: dict = {"evaluator": EVALUATOR, "detector": {"name": name, "kind": kind, "sha256": digest},
                    "data": {}, "metrics": {}, "dev_rows": []}
    for split in SPLITS:
        rows, meta, data_digest = _rows(Path(data_dir), split)
        mine = [r for r in rows if r["kind"] == kind]
        missed = sum(1 for m in meta.get("detector_misses", []) if m.get("expected_kind") == kind)
        proposed, baseline = [], []
        for r in mine:
            positive = r["label_kind"] == kind
            # A held-out row is never named in an error: Droid only ever sees held-out aggregates.
            fired = _fires(module, r["features"], f"dev row {r['row_id']}" if split == "dev" else "a held-out row")
            proposed.append((fired, positive))
            baseline.append((True, positive))
            if split == "dev":
                report["dev_rows"].append({"row_id": r["row_id"], "label_scenario": r["label_scenario"],
                                           "label_kind": r["label_kind"], "proposed": fired, "rules_only": True})
        report["data"][split] = {"file": SPLITS[split][0], "sha256": data_digest,
                                 "seeds": [s["seed"] for s in meta.get("seeds", [])], "rows": len(mine),
                                 "positives": sum(1 for _, p in proposed if p), "detector_misses": missed}
        report["metrics"][split] = {"proposed": _counts(proposed, missed), "rules_only": _counts(baseline, missed)}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True, help="chalk/evals/dataset")
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.detector, args.data)
    except (EvalError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"evaluator": EVALUATOR, "error": str(exc)}))
        return 2
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
