# SPDX-License-Identifier: Apache-2.0
"""Dev-time: walk the vendored ACP schema.json for identifiers the registry
does not know.

Three closed enums -- `StopReason`, `PermissionOptionKind` and the
`sessionUpdate` discriminator of `SessionUpdate` -- are read directly out of
their `$defs` `const` values and diffed against the registry's matching
list. A free-text regex heuristic ("looks like a method", ends `_chunk` or
`_update`, starts `allow_`/`reject_`) previously stood in for this and
missed any bare-word variant: `plan` and `tool_call` are exactly that shape
in the real schema, and no `StopReason` value has a recognisable suffix at
all, so a new stop reason could ship silently uncaught (hostile Fable 5
review, 2026-09-19). Methods have no single enumerating `$def`, so they stay
free-text.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "acp_cockpit" / "vendor" / "acp"

METHOD = re.compile(r"^(?:(?:session|fs|terminal|elicitation|\$)/[a-z_]+"
                    r"|initialize|authenticate|logout)$")


def _variant_consts(defs: dict, defname: str, problems: list[str],
                    discriminator: str | None = None) -> set[str]:
    """Every `const` a `oneOf`/`anyOf` variant of `defs[defname]` can take --
    directly, or (for a discriminated union) under
    `properties[discriminator].const`. A missing or restructured `$def`
    is appended to `problems` instead of raising, so a future schema
    reshuffle is reported like any other drift, not a crash."""
    node = defs.get(defname)
    if not isinstance(node, dict):
        problems.append(f"$defs/{defname} is missing or reshaped in the "
                        "schema -- update this script's assumptions")
        return set()
    out = set()
    for variant in node.get("oneOf", node.get("anyOf", [])):
        if not isinstance(variant, dict):
            continue
        if "const" in variant:
            out.add(variant["const"])
        if discriminator:
            tag = variant.get("properties", {}).get(discriminator, {})
            if isinstance(tag, dict) and "const" in tag:
                out.add(tag["const"])
    return out


def _diff(problems: list[str], label: str, schema_values: set[str],
         reg: dict, registry_key: str) -> None:
    known = set(reg.get(registry_key, [])) | set(
        reg.get(f"vendor_{registry_key}", []))
    novel = sorted(v for v in schema_values if v not in known)
    if novel:
        problems.append(f"{label} the registry's `{registry_key}` does not "
                        f"know: {', '.join(novel)}")


def _walk_methods(node, found: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "x-method" and isinstance(v, str):
                found.add(v)
            _walk_methods(v, found)
    elif isinstance(node, list):
        for x in node:
            _walk_methods(x, found)
    elif isinstance(node, str):
        # method names also live in titles/descriptions/x-method fields
        for x in re.findall(r"(?:session|fs|terminal|elicitation|\$)/[a-z_]+", node):
            found.add(x)


def find_problems(schema: dict, reg: dict) -> list[str]:
    problems: list[str] = []
    defs = schema.get("$defs", schema.get("definitions", {}))

    _diff(problems, "stop reasons", _variant_consts(defs, "StopReason", problems),
         reg, "stop_reasons")
    _diff(problems, "permission option kinds",
         _variant_consts(defs, "PermissionOptionKind", problems),
         reg, "permission_kinds")
    _diff(problems, "session update kinds",
         _variant_consts(defs, "SessionUpdate", problems,
                         discriminator="sessionUpdate"),
         reg, "update_kinds")

    known_methods = set()
    for key in ("to_agent_requests", "to_agent_notifications",
               "from_agent_requests", "from_agent_notifications",
               "vendor_to_agent_requests"):
        known_methods |= set(reg.get(key, []))
    found_methods: set[str] = set()
    _walk_methods(schema, found_methods)
    novel_methods = sorted(x for x in found_methods
                           if METHOD.match(x) and x not in known_methods)
    if novel_methods:
        problems.append("methods the registry does not know: " +
                        ", ".join(novel_methods))

    return problems


def main() -> int:
    schema = json.loads((VENDOR / "schema.json").read_text(encoding="utf-8"))
    reg = json.loads((VENDOR / "registry.json").read_text(encoding="utf-8"))
    problems = find_problems(schema, reg)
    if problems:
        print("SCHEMA HAS IDENTIFIERS THE REGISTRY DOES NOT KNOW:")
        for p in problems:
            print("  -", p)
        return 1
    print("registry covers all recognizable schema identifiers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
