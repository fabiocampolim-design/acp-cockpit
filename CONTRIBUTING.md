# Contributing to acp-cockpit

Thank you for considering a contribution. This file says how to report a
problem, how to propose a change, and the rules a change has to meet to be
merged. The machine-oriented description of the repository is `AGENTS.md`;
the human manual is `docs/USER_MANUAL.md`; the design decisions and their
trade-offs are in `docs/DESIGN.md`; the View/engine contract is
`docs/UI-PROTOCOL.md`.

## Reporting

Open an issue in this repository. The most useful reports carry: what you
did (the prompt, the button, the command), what you expected, what
happened, your platform, the agent adapter and its version (`npm ls -g`),
and — this is the one that makes a bug here reproducible — the relevant
part of the **session record** (`~/.acp-cockpit/records/<session>.jsonl`; the
`{}` button on a row shows the frame number). Records contain your
conversation: trim them before pasting. A protocol frame that this client
rendered wrongly, dropped, or failed to flag as unrecognized is a bug here;
an agent that behaves oddly while every frame was shown is a report for the
agent's adapter.

## Proposing a change

1. Open an issue first for anything larger than a typo, so the scope is
   agreed before the work is done.
2. Fork, branch, and keep the change to one topic.
3. **Failing-first test.** Every bug fix starts with a test that fails on
   the current code and passes on the fix; every feature comes with its
   tests. `pyflakes` must be clean over the whole tree.
4. Run the suite locally before opening the pull request:

   ```
   pip install -e .[dev]
   python -m pyflakes acp_cockpit tools scripts tests docs
   python -m pytest tests -q                      # engine, server, security, e2e (needs playwright)
   ACP_COCKPIT_CONTRACT=1 python -m pytest tests/contract/ -q   # against the real adapter; costs tokens
   python tools/check_schema_drift.py             # registry vs the pinned ACP schema
   ```

5. Keep the documentation in step: `README.md`, `AGENTS.md`,
   `docs/USER_MANUAL.md`, `docs/UI-PROTOCOL.md` and `CHANGELOG.md` describe
   the same program, and the suite fails when an event kind, a route, a CLI
   flag or the check count named in prose drifts from the code. Rebuild the
   manual with `python docs/build_manual.py` after editing it.
6. **Losslessness is the contract.** Nothing that crosses the wire may be
   dropped silently: new protocol data is recorded verbatim first and shown
   as `unrecognized`/`drift` until it is understood. A change that swallows
   a frame "because it is noise" will not be merged; move it out of the
   way (a chip, a drawer, a collapsed row) instead.
7. **The engine never names an agent.** Everything Claude-specific lives in
   `acp_cockpit/agents/claude.toml`; adding an agent is a new TOML profile
   (`acp_cockpit/agents/PROFILE-SCHEMA.md`), never a branch in `core/`.
8. Every new source file carries the SPDX header
   (`# SPDX-License-Identifier: Apache-2.0`).
9. Do not bump the version, `CITATION.cff` or tag a release in a pull
   request; the maintainer does that on merge.

## Contributions made with AI assistance

Welcome, on two conditions: say so in the pull request (which tool, what it
did), and state what *you* verified — the test you ran, the frame you
inspected, the screen you looked at. This repository was itself built with
an AI assistant under a check-everything contract (see `README.md`); the
same standard applies to contributions.

## Licensing

By submitting a contribution you agree that it is licensed under the
repository's licence (Apache License 2.0), as section 5 of that licence
provides for intentional submissions. Do not contribute code or text you do
not have the right to license that way, and do not add third-party material
(adapter sources, vendored SDKs, downloaded documents) to the tracked tree —
the adapter is a runtime dependency the user installs, never vendored.

## Conduct

Everyone interacting in this repository is expected to follow
`CODE_OF_CONDUCT.md`.
