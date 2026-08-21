# Development Guide

## CLI contract

- Keep the public Click root explicitly named `chatglance`.
- Use `chatstyle>=0.2.0,<0.3.0` and ChatStyle's `add_tree_option()` for the registered command tree; do not add a package-local tree renderer.
- Preserve top-level `--version`, `--tree`, and `--tree-brief`. The full tree includes signatures and the brief tree omits them while retaining the same nodes and descriptions.
- Give every visible group and leaf a one-line description that states its output or mutation boundary.
- Keep command bodies as thin adapters over reusable functions in the package modules.

## Environment and security contract

- Use `chatenv>=0.2.10,<0.3.0`, the registered `chatglance.config` provider, and ChatEnv's typed storage path for the active `CHATGLANCE_GITHUB_TOKEN` profile.
- Preserve token lookup precedence: explicit process environment, repo-local GitHub credential, active ChatGlance profile, then ChatGH's shared profile.
- Never print token values, git authorization headers, proxy credentials, account secrets, or unredacted quota data.
- Commands that mutate runtime config or user-level systemd state must keep that side effect explicit in help and tree summaries.

## Docs and Tests

- Use doc-first CLI testing.
- Put real CLI coverage under `tests/cli-tests/`.
- Put mock/fake CLI coverage under `tests/mock-cli-tests/`.
- Keep `README.md`, `docs/`, and `CHANGELOG.md` in sync with user-facing changes.

## Automation

- Keep automation small and reviewable.
- Prefer commands that can run in CI without interactive prompts.
- Ensure generated defaults are safe for local development.

## Local gates

```bash
python -m pytest -q
python -m build
python -m twine check dist/*
chatglance --version
chatglance --tree
chatglance --tree-brief
git diff --check
```

Releases follow PR, green exact-head checks, squash merge, a tag on the merged default-branch commit, trusted publishing, and clean PyPI install readback.
