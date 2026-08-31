# AGENTS.md — working rules for coding agents in this repo

## What this is

CLAUDIU 0.2: a browser ACP client (see `README.md` and
`docs/superpowers/specs/2026-08-31-claudiu-acp-design.md`). The v0.1
terminal-mirror app is archived in `archive/claudiu-v0.1/` (own `.git`,
gitignored) — read-only history, never modified.

## Layer rules (enforce these in review)

- `claudiu/core/` imports **stdlib only** and does no real I/O except
  `record.py` writing its own files; the outside world comes through
  `core/ports.py`. Never import tornado in core.
- `claudiu/ui/web/` consumes **only** `docs/UI-PROTOCOL.md`. If the UI
  needs something new, extend the doc and `tests/test_docs_sync.py` first.
- Everything agent-specific lives in `agents/*.toml`
  (`agents/PROFILE-SCHEMA.md`); the engine never names Claude.
- Anomalies, drift, and unrecognized data are **surfaced, never dropped** —
  that is the product's core guarantee; don't "clean up" those paths.

## Environment

- Bash `python` = 3.13 (has playwright — run the full suite here);
  PowerShell `python` = 3.14 (e2e import-skips there). Floor: 3.11.
- Full suite: `python -m pytest tests/ -q`. Real-adapter contract tier
  (costs tokens, needs `claude-code-acp` + credentials):
  `CLAUDIU_CONTRACT=1 python -m pytest tests/contract/ -q`.
- Always `python -m pyflakes claudiu tools tests` before committing.
- `tools/check_schema_drift.py` must stay green; when it reports novel
  identifiers after a schema bump, extend `vendor/acp/registry.json` and
  decide the UI treatment — that is the drift process working.

## House rules

- Never `git add -A` — stage explicit paths.
- Commits use the noreply identity (the KEEP/GITHUBIFY control documents
  on the dev machine govern publication).
- README's "Verified by N checks" is counted from a FULL suite run only.
- TDD: failing test first, then the code. Keep tasks small and committed.
- Update `CHANGELOG.md` for anything user-visible; releases bump
  `claudiu/__init__.py` + `pyproject.toml` together.
