"""Run the town into the database:

    python -m stormcash_sim --seed 42 --hours 72

Uses DATABASE_URL and SERVER_SIGNING_KEY_PEM from server/.env (or the
environment). Nessie is always off: simulated money is ledger-only.
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from stormcash.app import build_deps
from stormcash.config import load_settings

from . import outputs
from .engine import Params, Sim


def main() -> None:
    defaults = Params()
    ap = argparse.ArgumentParser(prog="stormcash_sim", description=__doc__.split("\n\n")[0])
    for f in dataclasses.fields(Params):
        flag = "--" + f.name.replace("_", "-")
        if f.type == "bool":
            ap.add_argument(flag, action=argparse.BooleanOptionalAction, default=getattr(defaults, f.name))
            continue
        kind = int if f.type in ("int", "int | None") else float
        ap.add_argument(flag, type=kind, default=getattr(defaults, f.name))
    ap.add_argument("--database-url", help="override DATABASE_URL")
    args = ap.parse_args()

    settings = load_settings()
    overrides = {"nessie_enabled": False, "background_tasks": False}
    if args.database_url:
        overrides["database_url"] = args.database_url
    deps = build_deps(dataclasses.replace(settings, **overrides))
    params = Params(**{f.name: getattr(args, f.name) for f in dataclasses.fields(Params)})
    try:
        sim = Sim(deps, params)
        summary = sim.run()
        folder = outputs.write(sim, summary)
        print(json.dumps(summary, indent=2))
        print(f"wrote {folder}/labels.json and stats.json")
    finally:
        deps.pool.close()


if __name__ == "__main__":
    main()
