# StormCash

When a disaster takes out towers and card readers, StormCash keeps phones paying local shops, and stops cheaters with no internet.

HackHarvard 2026. The full design lives in [`STORMCASH_BUILD_SPEC.md`](STORMCASH_BUILD_SPEC.md).

## Team

| Role | Who | Owns |
|---|---|---|
| **Person A — Mobile** (Mac 1) | Brian Maina ([@brianmmaina](https://github.com/brianmmaina)) | `mobile/`, WS0 TypeScript review, WS7 Photon, backup video |
| **Person B — Server, dashboard, integration** (Mac 2) | Alexandre Lugovoi ([@Alexlgvcode](https://github.com/Alexlgvcode)) | `server/`, `dashboard/`, `sim/`, `chalk/`, WS0 Python review |

## Repo layout

| Folder | What | Workstream |
|---|---|---|
| `spec/` | Test vectors shared by Python and TypeScript | WS0 |
| `server/` | FastAPI server, settlement, ledger, Nessie, StormDesk, Photon | WS2, WS5, WS7 |
| `mobile/` | Expo / React Native iPhone app | WS1 |
| `dashboard/` | React dashboard and public proof page | WS3 |
| `sim/` | 40-shop town simulator | WS4 |
| `chalk/` | Chalk features, resolvers and evals | WS6 |
| `fixtures/` | Replayed NWS alerts | — |

## Workflow

1. Pick an issue assigned to you. Each issue has a workstream label and a milestone (the schedule block it belongs to).
2. Pull the latest `main`, then branch off it with a `feat/` name, e.g. `feat/ws2-settlement`.
3. Commit your work on that branch and push it.
4. Open a pull request into `main`, fill out the PR template, and link the issue (`Closes #12`).
5. Whoever opened the PR merges it once it's ready (**Squash and merge** is the only option, so each PR becomes one commit on `main`).
6. GitHub deletes the branch automatically after the merge; locally, switch back to `main`, pull, and run `git fetch --prune`.

`main` is protected: no direct pushes, no force pushes, and no deleting it. Every change goes through a PR.

## Setup

Server secrets go in `server/.env` (copy [`server/.env.example`](server/.env.example)); never commit it. Per-folder setup is in each folder's README.
