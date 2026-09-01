# SPDX-License-Identifier: Apache-2.0
"""Scripted stand-in ACP agent. Usage: python fake_adapter.py fixture.json"""
import json
import sys

rules = json.loads(open(sys.argv[1], encoding="utf-8").read())
SESSION = "fake-session-1"


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    frame = json.loads(raw)
    if "method" not in frame:      # a response to one of OUR requests
        continue
    method, mid = frame["method"], frame.get("id")
    matched = False
    for rule in rules:
        if rule["on_method"] != method:
            continue
        if "if_prompt_contains" in rule:
            text = "".join(b.get("text", "") for b in
                           frame["params"].get("prompt", []))
            if rule["if_prompt_contains"] not in text:
                continue
        matched = True
        for err in rule.get("stderr", []):
            print(err, file=sys.stderr, flush=True)
        for note in rule.get("notify", []):
            note = json.loads(json.dumps(note).replace("$SESSION", SESSION))
            send(note)
        for req in rule.get("request", []):
            req = json.loads(json.dumps(req).replace("$SESSION", SESSION))
            send(req)
        if "respond" in rule:
            result = json.loads(
                json.dumps(rule["respond"]).replace("$SESSION", SESSION))
            send({"jsonrpc": "2.0", "id": mid, "result": result})
        break
    if not matched and mid is not None:
        send({"jsonrpc": "2.0", "id": mid,
              "error": {"code": -32601, "message": "no rule"}})
