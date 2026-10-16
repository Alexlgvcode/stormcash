# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Read the spec first

[`STORMCASH_BUILD_SPEC.md`](STORMCASH_BUILD_SPEC.md) is the source of truth. Read §0 before doing anything. If code and the spec disagree, the spec wins until the spec is changed; change it in the same commit as the code and say so in the commit message.

The rules from §0 that matter most:

- **One workstream, one folder.** Each session owns exactly one workstream (§4.3) and only edits its folder (plus `spec/` when the task says so).
- **The protocol (§7–§10) is frozen once `spec/vectors.json` exists.** Changing it means updating the spec, regenerating the vectors, and passing both the Python and TypeScript vector tests.
- **No AI in the money path.** StormDesk proposes; deterministic code freezes certificates; a human approves soft actions.
- **Honest UI copy.** Simulated is labeled "simulated", replayed is labeled "replayed", and no invented numbers anywhere.
- **Boring code.** Plain SQL with psycopg, plain FastAPI, plain React. No ORMs, Redis, or microservices.
- **Money is integer cents** (`*_cents`) everywhere except the Nessie boundary (`server/nessie.py: cents_to_dollars`). **Time is integer Unix seconds (UTC).**
- **Every risky thing ships with its fallback switch** (§22.4). **Done means demoable** on the real hardware.

## Workstreams and reviewers

Person A is Brian (@brianmmaina, mobile). Person B is Alex (@Alexlgvcode, server, dashboard, integration).

| ID | Workstream | Folder | Reviewer |
|---|---|---|---|
| WS0 | Protocol + test vectors | `spec/`, `server/stormcash/protocol/`, `mobile/src/protocol/` | B (Python), A (TypeScript) |
| WS1 | Mobile app | `mobile/` | A |
| WS2 | Server core | `server/` | B |
| WS3 | Dashboard | `dashboard/` | B |
| WS4 | Town simulator | `sim/` | B |
| WS5 | StormDesk agent | `server/stormcash/stormdesk/` | B |
| WS6 | Chalk features + evals | `chalk/` | B |
| WS7 | Photon agent | `server/stormcash/photon/` | A |

WS2 owns `server/stormcash/db.py`, `schema.sql` and `app.py`. Other server workstreams add routers in their own module, and B wires them in.

## Branches and pull requests

- Never commit directly to `main`; it is protected and only accepts pull requests.
- Branch off the latest `main` with a `feat/` prefix that names the workstream, e.g. `feat/ws2-settlement`.
- Reference the GitHub issue in the PR (`Closes #12`) and fill out `.github/pull_request_template.md`.
- PRs are squash-merged by their author.

## Git commits and pushes

- Do **not** add Claude as a collaborator, contributor, or co-author in any commit, push, or pull request.
- Never add `Co-Authored-By: Claude ...` trailers to commit messages.
- Never add "Generated with Claude Code" (or similar) lines to commit messages or PR descriptions.
- Commits and pushes should be attributed solely to the repository owner's git identity.
