"""Dev-time: walk the vendored ACP schema.json for identifiers the registry
does not know. Structure-agnostic: collects every string that looks like a
method name or enum value anywhere in the schema tree."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
schema = json.loads((ROOT / "vendor/acp/schema.json").read_text(encoding="utf-8"))
reg = json.loads((ROOT / "vendor/acp/registry.json").read_text(encoding="utf-8"))

known = set()
for key in ("to_agent_requests", "to_agent_notifications",
            "from_agent_requests", "from_agent_notifications",
            "update_kinds", "stop_reasons", "permission_kinds"):
    known |= set(reg[key])

found = set()
METHOD = re.compile(r"^(session|fs|terminal|elicitation)/[a-z_]+$")
WORD = re.compile(r"^[a-z][a-z_]+$")

def walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("const", "enum"):
                vals = v if isinstance(v, list) else [v]
                for x in vals:
                    if isinstance(x, str) and (METHOD.match(x) or WORD.match(x)):
                        found.add(x)
            walk(v)
    elif isinstance(node, list):
        for x in node:
            walk(x)

walk(schema)
novel = sorted(x for x in found if x not in known and
               (METHOD.match(x) or x.endswith("_chunk") or
                x.endswith("_update") or x.startswith(("allow_", "reject_"))))
if novel:
    print("SCHEMA HAS IDENTIFIERS THE REGISTRY DOES NOT KNOW:")
    for x in novel:
        print("  -", x)
    sys.exit(1)
print("registry covers all recognizable schema identifiers")
