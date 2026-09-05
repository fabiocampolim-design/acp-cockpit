# AGENTS.md — working rules for coding agents in this repo

## What this is

**acp-cockpit** (import name `acp_cockpit`): a browser client for AI coding
agents over the Agent Client Protocol. See `README.md` and
`docs/superpowers/specs/2026-08-31-claudiu-acp-design.md` (the approved
design; the file keeps the codename of the day it was written). The name the
running client shows on screen is configuration (`ACP_COCKPIT_UINAME`,
shipped as *ClaudIU*) and is never used to mean the project. The v0.1
terminal-mirror app that preceded the ACP pivot is kept out of this
repository, with its own history.

## Layout

```
acp_cockpit/core/       pure stdlib: JSON-RPC, ACP state machine, recorder,
                        sentinel, path policy, branding, transcript
acp_cockpit/server/     Tornado: auth, adapter subprocesses (job object /
                        process group), WebSocket bridge, REST
acp_cockpit/ui/web/     the bundled View: vanilla JS, speaks docs/UI-PROTOCOL.md
acp_cockpit/agents/     shipped agent profiles (*.toml) + PROFILE-SCHEMA.md;
                        `local-*.toml` here is never tracked; an installed
                        copy adds its own under ~/.acp-cockpit/agents/
acp_cockpit/vendor/acp/ the pinned ACP schema, its VERSION and the registry
acp_cockpit/uiname.toml the shipped on-screen name
tools/                  dev-time checks (schema drift)
scripts/                the daily upstream watch and its scheduler wrapper
docs/                   manual (md → html/pdf via build_manual.py), design,
                        UI protocol, manual test plan, watch reports, specs
```

Everything the server serves or reads at run time lives **inside the
package**: the wheel is the product, and a checkout must not be the only
thing that works (2026-09-05).

## Layer rules (enforce these in review)

- `acp_cockpit/core/` imports **stdlib only** and does no real I/O except
  `record.py` writing its own files; the outside world comes through
  `core/ports.py`. Never import tornado in core.
- `acp_cockpit/ui/web/` consumes **only** `docs/UI-PROTOCOL.md`. If the UI
  needs something new, extend the doc and `tests/test_docs_sync.py` first.
- Everything agent-specific lives in `acp_cockpit/agents/*.toml`
  (`PROFILE-SCHEMA.md`); the engine never names Claude.
- Anomalies, drift, unrecognized data and vendor updates are **surfaced,
  never dropped** — that is the product's core guarantee; don't "clean up"
  those paths. A frame the client recognises but does not render is still
  shown (`unrecognized` with the frame), never ignored.

## Environment

- Bash `python` = 3.13 (has playwright — run the full suite here);
  PowerShell `python` = 3.14 (e2e import-skips there). Floor: 3.11.
- Full suite: `python -m pytest tests/ -q`. Real-adapter contract tier
  (costs tokens, needs the adapter named in `acp_cockpit/agents/claude.toml`
  — `claude-agent-acp` — plus credentials):
  `ACP_COCKPIT_CONTRACT=1 python -m pytest tests/contract/ -q`.
- Always `python -m pyflakes acp_cockpit tools scripts tests docs` before
  committing.
- `tools/check_schema_drift.py` must stay green; when it reports novel
  identifiers after a schema bump, extend
  `acp_cockpit/vendor/acp/registry.json` and decide the UI treatment — that
  is the drift process working. A kind the installed adapter emits outside
  the schema goes in `vendor_update_kinds`, with a row in the View.
- The e2e server is module-scoped and shared: a browser test asks for the
  launcher through `open_launcher` (which closes stray sessions and waits for
  the reattach to finish), scopes every wait to `.pane:not([hidden])`, and
  waits for the **state it asserts**, never for the element that precedes it.

## House rules

- Never `git add -A` — stage explicit paths.
- Commits use the noreply identity (the KEEP/GITHUBIFY control documents
  on the dev machine govern publication).
- README's "Verified by N checks" is a **static count** of `def test_`
  under `tests/` minus the contract tier (`tests/test_docs_guard.py`
  computes it); no `parametrize`.
- TDD: failing test first, then the code. Keep tasks small and committed.
- Update `CHANGELOG.md` for anything user-visible; releases bump
  `acp_cockpit/__init__.py`, `pyproject.toml` **and `CITATION.cff`**
  together, rebuild the manual (`python docs/build_manual.py`, whose PDF is
  byte-reproducible), push, wait for CI to be **green**, then tag.
- The daily watch (`scripts/watch_upstream.py`) is the first thing to read
  after any gap: this product depends on an adapter that ships several
  times a week.
