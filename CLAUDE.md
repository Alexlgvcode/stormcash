# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Git commits and pushes

- Do **not** add Claude as a collaborator, contributor, or co-author in any commit, push, or pull request.
- Never add `Co-Authored-By: Claude ...` trailers to commit messages.
- Never add "Generated with Claude Code" (or similar) lines to commit messages or PR descriptions.
- Commits and pushes should be attributed solely to the repository owner's git identity.

## Branches and pull requests

- Never commit directly to `main`; it is protected and only accepts pull requests.
- Create branches off the latest `main` with a `feat/` prefix (e.g. `feat/login-page`).
- PRs are squash-merged by their author; fill out `.github/pull_request_template.md` when opening one.
