import json
import os
import subprocess
import sys


def rpc(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" not in msg:
        return None
    return json.loads(proc.stdout.readline())


def test_mcp_stdio_session(site, tmp_path):
    (tmp_path / "config.json").write_text('{"allow_private": true}', encoding="utf-8")
    env = dict(os.environ, ZORKO_HOME=str(tmp_path))
    proc = subprocess.Popen([sys.executable, "-m", "zorko", "mcp"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env)
    try:
        r = rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "t", "version": "0"}}})
        assert r["result"]["serverInfo"]["name"] == "zorko"
        assert "untrusted" in r["result"]["instructions"]
        rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        names = {t["name"] for t in tools}
        assert {"open", "look", "click", "type", "find", "read", "screenshot"} <= names

        r = rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "open", "arguments": {"url": site + "/shop.html"}}})
        text = r["result"]["content"][0]["text"]
        assert "Скважинные насосы" in text and not r["result"]["isError"]

        r = rpc(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                       "params": {"name": "click", "arguments": {"id": 43}}})
        assert r["result"]["isError"] and "confirm" in r["result"]["content"][0]["text"]

        r = rpc(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                       "params": {"name": "screenshot", "arguments": {}}})
        img = r["result"]["content"][0]
        assert img["type"] == "image" and img["mimeType"] == "image/jpeg" and len(img["data"]) > 1000

        r = rpc(proc, {"jsonrpc": "2.0", "id": 6, "method": "nope"})
        assert r["error"]["code"] == -32601
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
