import json

import httpx
import pytest

from tests.tools.helpers import make_cfg
from ultron.mcp_server import McpServer
from ultron.memory import Vault
from ultron.tools.registry import build_registry


def make_server(tmp_path, core_handler=None):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    reg = build_registry(cfg, v, lambda t: None, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
    handler = core_handler or (lambda r: httpx.Response(200, json={"allow": True, "input": {}}))
    core = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return McpServer(reg, "http://core", core)


async def test_initialize_echoes_protocol(tmp_path):
    s = make_server(tmp_path)
    r = await s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert r["id"] == 1
    assert r["result"]["protocolVersion"] == "2025-06-18"
    assert "tools" in r["result"]["capabilities"]


async def test_notification_has_no_reply(tmp_path):
    s = make_server(tmp_path)
    assert await s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


async def test_tools_list_includes_permission_tool(tmp_path):
    s = make_server(tmp_path)
    r = await s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"abrir_jogo", "aprovar_permissao"} <= names
    assert all("inputSchema" in t for t in r["result"]["tools"])


async def test_tools_call(tmp_path):
    s = make_server(tmp_path)
    r = await s.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "obsidian_pendencias", "arguments": {}}})
    assert r["result"]["content"][0]["type"] == "text"
    assert r["result"]["isError"] is False


async def test_tools_call_error_flagged(tmp_path):
    s = make_server(tmp_path)
    r = await s.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "abrir_app", "arguments": {}}})
    assert r["result"]["isError"] is True


async def test_unknown_method(tmp_path):
    s = make_server(tmp_path)
    r = await s.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
    assert r["error"]["code"] == -32601


async def _perm(tmp_path, handler):
    s = make_server(tmp_path, handler)
    r = await s.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
        "name": "aprovar_permissao", "arguments": {"tool_name": "Bash", "input": {"command": "dir"}}}})
    return json.loads(r["result"]["content"][0]["text"])


async def test_permission_allow(tmp_path):
    seen = []
    def h(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"allow": True, "input": {"command": "dir"}})
    out = await _perm(tmp_path, h)
    assert out == {"behavior": "allow", "updatedInput": {"command": "dir"}}
    assert seen[0] == {"tool_name": "Bash", "input": {"command": "dir"}, "chat": None}


async def test_permission_deny(tmp_path):
    out = await _perm(tmp_path, lambda r: httpx.Response(200, json={"allow": False, "input": {}}))
    assert out["behavior"] == "deny" and out["message"]


async def test_permission_core_down_denies(tmp_path):
    def h(req):
        raise httpx.ConnectError("down")
    out = await _perm(tmp_path, h)
    assert out["behavior"] == "deny"
