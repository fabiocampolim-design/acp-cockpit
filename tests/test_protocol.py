# SPDX-License-Identifier: Apache-2.0
import json
from acp_cockpit.core.protocol import JsonRpcConn


def make_conn(log):
    return JsonRpcConn(
        on_request=lambda i, m, p: log.append(("req", i, m, p)),
        on_notification=lambda m, p: log.append(("note", m, p)),
        on_anomaly=lambda c, d, r: log.append(("anomaly", c)),
    )


def test_request_response_matching():
    log, results = [], []
    conn = make_conn(log)
    rid = conn.request("initialize", {"protocolVersion": 1},
                       lambda res, err: results.append((res, err)))
    out = conn.take_outgoing()
    frame = json.loads(out[0])
    assert frame == {"jsonrpc": "2.0", "id": rid, "method": "initialize",
                     "params": {"protocolVersion": 1}}
    conn.feed(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"ok": 1}}))
    assert results == [({"ok": 1}, None)]


def test_error_response_delivered():
    log, results = [], []
    conn = make_conn(log)
    rid = conn.request("session/new", {}, lambda r, e: results.append((r, e)))
    conn.feed(json.dumps({"jsonrpc": "2.0", "id": rid,
                          "error": {"code": -32603, "message": "boom"}}))
    assert results[0][0] is None and results[0][1]["code"] == -32603


def test_incoming_request_and_notification_dispatch():
    log = []
    conn = make_conn(log)
    conn.feed(json.dumps({"jsonrpc": "2.0", "id": 9,
                          "method": "session/request_permission",
                          "params": {"x": 1}}))
    conn.feed(json.dumps({"jsonrpc": "2.0", "method": "session/update",
                          "params": {"y": 2}}))
    assert log[0] == ("req", 9, "session/request_permission", {"x": 1})
    assert log[1] == ("note", "session/update", {"y": 2})


def test_respond_and_error_frames():
    conn = make_conn([])
    conn.respond(9, {"outcome": {"outcome": "cancelled"}})
    conn.error(10, -32601, "unsupported")
    a, b = (json.loads(x) for x in conn.take_outgoing())
    assert a["id"] == 9 and "result" in a
    assert b["error"]["code"] == -32601


def test_malformed_and_unmatched_are_anomalies_not_crashes():
    log = []
    conn = make_conn(log)
    conn.feed("this is not json")
    conn.feed(json.dumps({"jsonrpc": "2.0", "id": 777, "result": {}}))
    conn.feed(json.dumps([1, 2, 3]))
    cats = [x[1] for x in log if x[0] == "anomaly"]
    assert cats == ["malformed", "unmatched-id", "malformed"]
