# chalk/evals: StormDesk triage evaluations (spec §15.3)

One Chalk Evaluation scores StormDesk's triage of detector candidates against the simulator's ground truth, next to the §13 rules-only baseline ("flag every candidate with its default action"). The Evals tab (#38, §18.5) renders the files in `results/`. Every number in them comes from a real Chalk run.

## What's here

| File | Runs where | What it does |
|---|---|---|
| `build_dataset.py` | server venv | Runs 5 seeded towns into local eval databases and writes `dataset/stormdesk_triage.jsonl` (one row per candidate) and `dataset/meta.json` |
| `stack.py` | server venv | Starts one server per seed town, the gateway and a cloudflared quick tunnel (`up` / `status` / `down`) |
| `gateway.py` | local | The tunnel's only target: routes a row to its seed's server and turns a run into a job the task polls |
| `task_stormdesk.py` | Chalk | The task: StormDesk on one candidate through the tunnel, returns the Flag JSON |
| `task_rules_only.py` | Chalk | The rules-only baseline as a task (deterministic, no server) |
| `task_replay.py` | Chalk | The fallback's task: returns the output `run_local.py` already produced |
| `eval_scorers.py` | Chalk | `valid-json` (built-in), `kind-correct`, `action-correct`, `no-false-flag`, `citations-valid` |
| `run_eval.py` | chalk venv | Uploads the dataset, creates and runs the Evaluation, saves `results/<timestamp>-<runner>.json` |
| `run_local.py` | chalk venv | Fallback (§22.4): runs StormDesk locally, uploads the outputs, scores them in Chalk |
| `results.py` | local | Turns a run's result dataset into the results file |

The Chalk files are self-contained on purpose: Chalk ships each one to its worker as a single file. Importing any of them deploys its functions, so `evals` is in `chalk/.chalkignore` and every side effect sits under `if __name__ == "__main__":`. The tests import them with `CHALK_REMOTE_FUNCTION=1`, which deploys nothing.

## The dataset

`build_dataset.py` runs seeds **42, 7, 13, 99 and 2026** (72 h from a fixed T0, 2026-10-14 00:00 UTC) with every §16.4 scenario planted, then takes every candidate the detectors raised. The labels come from the simulator's `labels.json`, matched by subject:

- `label_kind`, `label_action`: the subject's `expected_kind` / `expected_action` (all traps: `none` / `none`).
- `label_scenario`: `colluder`, `stolen_phone`, `dark_region`, `trap_remote_shop`, `trap_victim_shop`, `trap_stockup`, `trap_quiet_region` (`trap_clock_drift` never raises a candidate, by design). A subject the simulator didn't plant would be `honest`; none occurred.
- `honest_subject`: true when flagging the subject would be a false flag (every trap).
- `features`: the candidate's frozen feature snapshot (JSON). `row_id` is `seed:candidate_id`.

The same seeds always give the same rows byte for byte. With these seeds and the #82 simulator there are **43 rows (20 honest)**, under the spec's ~60 target. `meta.json` also lists the labelled subjects the detectors never raised (3 with these seeds: two colluders and a stolen phone). Which subjects the detectors miss depends on the time of day the scenarios land on; T0 was fixed before any run. Neither runner ever sees those subjects, so the Evals tab should say so rather than count them.

**One database per seed, all local.** The detectors compare a shop with its neighbours, and the towns of two seeds overlap on the same grid, so each seed gets its own database (`stormcash_eval_<seed>`). They live on a local Postgres, never on the hosted Neon demo database, which keeps seed 42 for the demo. `build_dataset.py` refuses a non-local host. The towns are signed with a throwaway eval server key in `.state/server_key.pem`; the demo server's key is never read.

```bash
docker run -d --name stormcash-evals-pg -e POSTGRES_PASSWORD=postgres -p 5433:5432 postgres:16
uv venv server/.venv --python 3.11 && uv pip install --python server/.venv/bin/python -e "./server[dev]" -e ./sim
server/.venv/bin/python chalk/evals/build_dataset.py            # ~1 min; reuses towns already seeded
server/.venv/bin/python chalk/evals/build_dataset.py --rebuild  # drop and re-seed
```

`schema.sql` and every file in `server/migrations/` are applied to each database (the migrations are safe to run twice).

## The eval stack (for the StormDesk task)

```bash
brew install cloudflared                                   # no account needed: a quick tunnel
server/.venv/bin/python chalk/evals/stack.py up --runner fake
server/.venv/bin/python chalk/evals/stack.py up --runner droid --model claude-sonnet-5-5 --max-credits 2500000
server/.venv/bin/python chalk/evals/stack.py down
```

```
Chalk task ──https──▶ trycloudflare.com ──▶ gateway :8800 ──▶ server :8100 (seed 42 DB)
 (sd-stormdesk-triage)                       (bearer token)  ├─▶ server :8101 (seed 7 DB)
                                                             └─▶ ... one per seed
```

- **Servers.** `uvicorn --factory stormcash.app:create_app` per seed, with `DATABASE_URL` set to that seed's local database and `NESSIE_DISABLED=1 PHOTON_DISABLED=1 CHALK_DISABLED=1 BACKGROUND_TASKS=0 STORMDESK_AUTO=0`. The only StormDesk runs are the ones the eval asks for. `CHALK_DISABLED=1` is needed because Chalk's `neon_stormcash` integration points at the demo database, not the eval towns: `query_features` answers from the eval database instead (`postgres_fallback`, the candidate's frozen features).
- **Runner.** `--runner fake` is the labelled fake runner (§14.7a), which applies the rules-only logic through the real tools and citation check. `--runner droid` is the real agent: it reads `FACTORY_API_KEY` from the main checkout's `server/.env` (`--factory-env`) and gives it to the servers only. Without a key, Droid uses the `droid` CLI's login.
- **Gateway** (`gateway.py`, stdlib). It routes `{seed, candidate_id}` to that seed's server and calls the real `POST /v1/stormdesk/run`. It answers with a job id the task polls, because an agent run can outlast the tunnel's ~100 s response limit. It serves only `POST /runs` and `GET /runs/<id>`, and only with the bearer token in `.state/gateway_token`, so the tunnel exposes nothing else of the server. Its output is the Flag JSON plus `_run`, the server's verdict: `runner`, `citations_valid`, `missing_citations`, `fallback_from_droid` and `run_id`.
- **Droid guard** (`--runner droid` needs `--model` and `--max-credits`). Droid keeps every session under `~/.factory/sessions/<server cwd>/<session id>.jsonl` and `.settings.json`, with each message's `modelId` and the session's `factoryCredits`. The gateway reads them:
  - each row's `_run` gets `session_id`, `models_used` and `factory_credits`;
  - `GET /stats` (and `stack.py status`) sums every session the eval servers wrote since the gateway started, retried attempts included.
  - Its breaker trips, and new rows get 409, as soon as a session used another model (Factory moves sessions to "Droid Core" when Standard Usage runs out), a row fell back to the fake runner, a row's session can't be read, or the credit cap is reached. A tripped or partial run is `complete: false` and never a StormDesk result. Every row of a StormDesk result comes from the one named model.
  - Price a run first: a few rows with the same runner, then the per-row credits times 48.
- **Tunnel.** `cloudflared tunnel --url http://127.0.0.1:8800`. The URL changes on every `up`; `run_eval.py` reads it from `.state/stack.json` and deploys the task with it.

## Running

```bash
cd chalk && uv sync
uv run python evals/run_eval.py rules_only   # the baseline, entirely in Chalk
uv run python evals/run_eval.py stormdesk    # needs stack.py up (with the tunnel)
uv run python evals/run_local.py             # fallback: needs stack.py up (--no-tunnel is enough)
uv run python evals/run_eval.py resummarize <run_id>   # rewrite a run's results file from its result dataset
uv run pytest
```

Each run creates an Evaluation in the **StormCash** suite pinned to the same dataset revision (`stormdesk-triage`; a new revision only when the JSONL changes), runs it, reads the result dataset, and writes `results/<UTC timestamp>-<runner>.json` (`-local` for `run_local.py`). A run that doesn't succeed saves nothing.

### Scorers

| Scorer | Score |
|---|---|
| `valid-json` | built-in `json_valid`: the output parses as JSON. A run with no Flag returns plain text, so it fails |
| `kind-correct` | `output.kind == label_kind` |
| `action-correct` | `output.proposed_action == label_action` |
| `no-false-flag` | if `honest_subject`: `kind == "none"`, or severity `info` with action `none`. Other rows pass (nothing to falsely flag; metadata `applies: false`), so the results file also gives its mean over honest rows (`mean_honest_rows`) and the honest-only false-flag rate |
| `citations-valid` | the server's §14.7 citation check, run against the eval database when the Flag was stored (`_run.citations_valid`). Not in the rules-only evaluation: the baseline cites nothing (n/a) |

Every scorer returns exactly one score per row. Chalk computes no score summary (no averages in the dashboard) for a run whose scorers return lists; we checked this on Oct 17 by rescoring the same run with scalar scorers only.
Every function scorer gives 0 to an output that isn't a Flag. `summary-quality` (LLM judge, a stretch goal) isn't built: the environment's Model Gateway has no models (`chalk router model list`).

## Honesty rules for results

- **The runner is read from the outputs, never from configuration.** `rules_only` is the baseline column. `droid` means every row was answered by Droid with no fallback, and every row's session (and every audited session) used the one model asked for. It is the only result that may fill the StormDesk column (`table_column: "stormdesk"`, `is_agent_result: true`), and only when `complete` (no task errors, breaker not tripped).
- **A fake-runner result is saved with `runner: "fake"` and `table_column: null`.** So is a Droid run where any row fell back to the fake runner (`runner: "mixed"`, or `fake` if every row did). Neither is ever a StormDesk score. The fake runner proves the pipeline only.
- Rows with no Flag or a task error stay in the denominators as failures (`rows_without_flag`, `task_errors`).

## Agent versions

- **v1** (`20261017T135917Z-droid.json`, Chalk run `a91828a0-342b-4030-b046-a926fe5ade9d`): StormDesk's prompt as of #81, the first real run.
- **prompt v2** (`--label "prompt v2"`): one general prompt fix (#11, #86), written **after reading v1's errors on this same dataset**. So v2 is not a blind holdout: its score on these rows is an optimistic estimate.
- **prompt v2, Oct 17: incomplete** (`20261017T144002Z-droid-prompt-v2-incomplete.json`, Chalk run `aca3204b-db75-4908-a388-4594d4ee97a7`). Before it ran:
  - every eval server was shown to run `PROMPT_VERSION` 2 (the `stack.py` check);
  - a check row confirmed `prompt_version` 2 and `claude-sonnet-5-5`.

  v2 rows cost more than v1's (about 45k credits each), so the 1.6M admission cap refused 11 of the 43 rows. That's 1,481,125 credits including the 37,620-credit check row. All 32 answered rows were prompt v2 on `claude-sonnet-5-5`. The file is `complete: false`, `table_column: null`: a record, not a score. The StormDesk column stays v1. Both files stay. The Evals tab shows the newest complete run and lists the older one with its Chalk run id.
- **Discarded, Oct 17:** Chalk run `b30fd876-16e0-4002-b118-6bcfe116c0f7` (evaluation "… · prompt v2", 1,314,180 credits) was **not** prompt v2. The v1 stack's servers had survived `stack.py down` (uvicorn hung on SIGTERM after Droid runs), the new servers couldn't bind their ports, and the stale prompt-v1 servers answered every row. The `prompt_version` check caught it: no row reported version 2, so it was saved as `mixed` and never shown. Its file isn't committed. `stack.py` now refuses to start while any eval port is taken, checks every server it starts is still alive, and SIGKILLs a server that ignores SIGTERM.

```bash
uv run python evals/run_eval.py stormdesk --label "prompt v2" --label-note "written after reading v1's errors on this dataset: not a blind holdout"
```

## Held-out seeds (chosen Oct 17, before any held-out row was built or run)

**Seeds 1, 2 and 3**, the same fixed T0 and 72 h as the main dataset. They were chosen before their towns were built and before any prompt-v2 result was seen. No dataset, simulator output, or StormDesk prompt (v1 or v2) has ever used them, so prompt v2 was written without seeing their rows. Their rows are a separate dataset (`dataset/stormdesk_triage_heldout.jsonl`), and their results are a separate section ("held-out seeds"), never mixed into the main comparison. If the credit cap can't cover all three, the run uses seeds in the order 1, 2, 3, decided before it starts.

## Results file (for the Evals tab, #38)

```jsonc
{
  "schema_version": 1, "eval": "stormdesk-triage",
  "runner": "rules_only | droid | fake | mixed",
  "runner_label": "Rules-only baseline",          // display text, says "not an agent" for fake
  "is_agent_result": false,
  "table_column": "rules_only | stormdesk | null", // null: never shown in the comparison table
  "model": null,                                   // the model the servers asked Droid for
  "mode": "chalk_task | run_local",
  "timestamp": 1792203855, "timestamp_iso": "2026-10-17T02:24:15Z", "git_sha": "...",
  "chalk": {"environment_id", "suite", "suite_id", "evaluation_id", "evaluation_name", "run_id", "status",
            "task_function_version_id", "dataset_id", "dataset_revision_id",
            "result_dataset_id", "result_dataset_revision_id", "created_at", "completed_at"},
  "dataset": {"name", "rows", "honest_rows", "seeds", "scenarios", "detector_misses", "sha256"},
  "runners_seen": {"rules_only": 48},
  "scorers": {"kind-correct": {"in_evaluation": true, "mean": 0.0, "scored_rows": 48, "errors": 0},
              "no-false-flag": {"...": 0, "mean_honest_rows": 0.0}, "...": {}},
  "metrics": {
    "real_caught":      {"caught", "total", "recall"},        // non-honest rows with the right kind and action
    "colluders_caught": {"caught", "total", "recall"},
    "honest_flagged":   {"flagged", "total", "false_flag_rate"},
    "precision_by_kind": {"merchant_silence": {"flagged", "correct", "precision"}, "cap_drain": {}, "region_dark": {}},
    "citations_valid":  {"valid", "checked", "rate"} | null,  // null for rules-only (n/a)
    "pool_cents": {"note", "at_colluders", "held_correctly", "held_from_honest_shops"},
    "rows_without_flag", "task_errors", "fallback_from_droid"
  },
  "per_scenario": [{"scenario", "rows", "honest", "label_kind", "label_action", "caught", "dismissed",
                    "flagged", "kind_correct", "action_correct", "without_flag"}],
  "rows": [{"row_id", "seed", "candidate_id", "kind", "subject_id", "subject_name", "label_scenario",
            "label_kind", "label_action", "honest_subject", "output_kind", "output_severity", "output_action",
            "summary", "reasoning", "evidence_ids", "exposure_cents", "runner", "server_run_id",
            "citations_valid", "error", "scores": {"kind-correct": 1.0, "...": null}}]
}
```

- "Trap cases it got right" are the `rows` with `honest_subject` and `scores["no-false-flag"] == 1`.
- `pool_cents` is the pool money in each `merchant_silence` candidate's 6 h window, from its frozen features.
- The Chalk dashboard shows the same run under **Evaluations → StormCash**.

## Cost note

Each deployed function keeps one replica running (the default). `chalk function list` shows them. Delete them after the hackathon if they aren't needed; evaluations that use them can't be re-run once they're gone.
