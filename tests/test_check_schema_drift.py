# SPDX-License-Identifier: Apache-2.0
"""tools/check_schema_drift.py had no test at all: its `novel` filter kept
only strings matching a method regex or ending `_chunk`/`_update` or
starting `allow_`/`reject_`. A bare-word `SessionUpdate` variant like `plan`
or `tool_call`, or any `StopReason` variant, matches none of those, so it
was collected and then silently dropped from the report -- the tool would
print "registry covers all recognizable schema identifiers" while missing a
real gap (hostile Fable 5 review, 2026-09-19)."""
import json
from pathlib import Path

from tools.check_schema_drift import find_problems

ROOT = Path(__file__).resolve().parents[1]
REAL_SCHEMA = json.loads(
    (ROOT / "acp_cockpit" / "vendor" / "acp" / "schema.json").read_text(encoding="utf-8"))
REAL_REGISTRY = json.loads(
    (ROOT / "acp_cockpit" / "vendor" / "acp" / "registry.json").read_text(encoding="utf-8"))


def _schema(stop_reasons=(), update_kinds=(), permission_kinds=()):
    return {"$defs": {
        "StopReason": {"oneOf": [{"const": c} for c in stop_reasons]},
        "PermissionOptionKind": {"oneOf": [{"const": c} for c in permission_kinds]},
        "SessionUpdate": {"discriminator": {"propertyName": "sessionUpdate"},
                          "oneOf": [{"properties": {"sessionUpdate": {"const": c}}}
                                    for c in update_kinds]},
    }}


EMPTY_REGISTRY = {"stop_reasons": [], "permission_kinds": [], "update_kinds": []}


def test_the_real_pinned_schema_and_registry_agree():
    """Regression: `tools/check_schema_drift.py` must stay green (AGENTS.md).
    This is what CI actually runs it for -- prove it stays that way."""
    assert find_problems(REAL_SCHEMA, REAL_REGISTRY) == []


def test_a_bare_word_stop_reason_missing_from_the_registry_is_reported():
    problems = find_problems(
        _schema(stop_reasons=["budget_exceeded"]), EMPTY_REGISTRY)
    assert any("budget_exceeded" in p for p in problems)


def test_a_bare_word_update_kind_missing_from_the_registry_is_reported():
    # `plan` and `tool_call` are exactly this shape in the real schema: no
    # `_chunk`/`_update` suffix, no `allow_`/`reject_` prefix.
    problems = find_problems(
        _schema(update_kinds=["plan"]), EMPTY_REGISTRY)
    assert any("plan" in p for p in problems)


def test_a_permission_kind_missing_from_the_registry_is_reported():
    problems = find_problems(
        _schema(permission_kinds=["allow_forever"]), EMPTY_REGISTRY)
    assert any("allow_forever" in p for p in problems)


def test_nothing_novel_means_no_problems():
    schema = _schema(stop_reasons=["end_turn"], update_kinds=["plan"],
                     permission_kinds=["allow_once"])
    registry = {"stop_reasons": ["end_turn"], "update_kinds": ["plan"],
               "permission_kinds": ["allow_once"]}
    assert find_problems(schema, registry) == []


def test_a_renamed_def_is_reported_instead_of_crashing():
    """A future schema bump could rename or restructure a `$def` outright.
    That should surface as a finding for a person to look at, not an
    unrelated KeyError/TypeError from deep inside the walk."""
    problems = find_problems({"$defs": {}}, EMPTY_REGISTRY)
    assert any("StopReason" in p for p in problems)
