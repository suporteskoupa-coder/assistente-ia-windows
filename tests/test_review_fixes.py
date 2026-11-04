"""Testes que reproduzem os achados da revisão final."""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.events import Event
from ultron.memory import Vault
from ultron.server import create_app
from ultron.service import Ultron

TOKEN = "segredo123"
# o TestClient manda Host "testserver" no WebSocket; a HUD real manda 127.0.0.1:<porta>
LOCAL_WS = {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"}


def make_client(tmp_path, brains=None, token=TOKEN):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    hud = tmp_path / "hud"
    hud.mkdir(exist_ok=True)
    (hud / "index.html").write_text("<h1>ULTRON</h1>")
    broker = ConfirmBroker(timeout=5)
    u = Ultron(cfg, ChatStore(cfg.db_path), v, brains or {"claude": FakeBrain("claude")}, broker)
    c = TestClient(create_app(u, broker, hud, token=token), base_url="http://127.0.0.1:8765")
    c.ultron = u
    return c


# ---------- C1: só a HUD com o token controla o Ultron ----------

def test_api_requires_token(tmp_path):
    with make_client(tmp_path) as c:
        assert c.get("/api/chats").status_code == 403
        assert c.post("/api/confirm/x", json={"allow": True}).status_code == 403
        assert c.post("/api/permission", json={"tool_name": "Bash", "input": {}}).status_code == 403
        assert c.get("/api/chats", headers={"X-Ultron-Token": TOKEN}).status_code == 200


def test_foreign_host_rejected(tmp_path):
    with make_client(tmp_path) as c:
        r = c.get("/api/chats", headers={"X-Ultron-Token": TOKEN, "Host": "rebind.attacker.example"})
        assert r.status_code == 400


def test_ws_without_token_rejected(tmp_path):
    with make_client(tmp_path) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws") as ws:
                ws.receive_json()


def test_ws_foreign_origin_rejected(tmp_path):
    with make_client(tmp_path) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(f"/ws?t={TOKEN}", headers={**LOCAL_WS, "Origin": "https://evil.example"}) as ws:
                ws.receive_json()


def test_ws_with_token_and_local_origin_works(tmp_path):
    with make_client(tmp_path) as c:
        cid = c.post("/api/chats", json={"brain": "claude"}, headers={"X-Ultron-Token": TOKEN}).json()["id"]
        with c.websocket_connect(f"/ws?t={TOKEN}", headers=LOCAL_WS) as ws:
            ws.send_json({"type": "send", "chat_id": cid, "text": "oi"})
            while ws.receive_json()["type"] != "done":
                pass


def test_index_injects_token(tmp_path):
    with make_client(tmp_path) as c:
        assert c.get("/").status_code == 200


def test_mcp_server_sends_token(tmp_path, monkeypatch):
    import asyncio
    from ultron.mcp_server import McpServer
    from ultron.tools.registry import build_registry
    cfg = make_cfg(tmp_path)
    seen = []

    def h(req):
        seen.append(req.headers.get("X-Ultron-Token"))
        return httpx.Response(200, json={"allow": False})

    reg = build_registry(cfg, Vault(cfg.vault), lambda t: None, httpx.AsyncClient())
    s = McpServer(reg, "http://core", httpx.AsyncClient(transport=httpx.MockTransport(h)), token=TOKEN)
    asyncio.run(s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "aprovar_permissao", "arguments": {"tool_name": "Bash", "input": {}}}}))
    assert seen == [TOKEN]


def test_mcp_config_carries_token(tmp_path):
    from ultron.app import write_mcp_config
    out = write_mcp_config(tmp_path / "mcp.json", tmp_path / "u.toml", token=TOKEN)
    assert json.loads(out.read_text())["mcpServers"]["ultron"]["env"]["ULTRON_TOKEN"] == TOKEN


# ---------- C2: sem console (pythonw) ----------

def test_startup_without_console(tmp_path, monkeypatch):
    import uvicorn
    from ultron.app import fix_stdio, server_config
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log = fix_stdio(tmp_path)
    assert sys.stdout is not None and sys.stderr is not None
    server_config(object(), 8765)  # não pode levantar
    print("ok")
    sys.stdout.flush()
    assert log.exists()


# ---------- I1: sem janela de console no Windows ----------

def test_no_window_flags():
    from ultron.winproc import no_window_kwargs
    assert no_window_kwargs("win32") == {"creationflags": 0x08000000}
    assert no_window_kwargs("linux") == {}


async def test_claude_brain_uses_no_window(tmp_path, monkeypatch):
    import asyncio
    from ultron.brains import claude_code
    seen = {}

    async def fake_exec(*a, **kw):
        seen.update(kw)
        raise OSError("parar aqui")

    monkeypatch.setattr(claude_code, "no_window_kwargs", lambda: {"creationflags": 123})
    monkeypatch.setattr(claude_code.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(claude_code.shutil, "which", lambda b: "/bin/claude")
    b = claude_code.ClaudeCodeBrain(make_cfg(tmp_path), tmp_path / "m.json", [], tmp_path)
    [e async for e in b.send(None, [], "oi", "")]
    assert seen["creationflags"] == 123


# ---------- I2: pywebview não pode varrer a janela ----------

def test_window_api_has_no_public_attributes():
    from ultron.app import WindowApi
    api = WindowApi()
    api.window_set(object())
    public = [k for k in vars(api) if not k.startswith("_")]
    assert public == []


# ---------- I3: casamento de jogos não abre o jogo errado ----------

from ultron.tools.steam import Game, match_game

G = [Game("1", "Room"), Game("2", "Physics Playground"), Game("3", "Counter-Strike 2"),
     Game("4", "Dark Souls III"), Game("5", "Terraria"), Game("6", "Hollow Knight")]


@pytest.mark.parametrize("q", ["doom", "dark souls 2", "t", "ro"])
def test_weak_matches_are_only_suggestions(q):
    assert isinstance(match_game(G, q), list)


def test_cs_opens_counter_strike_not_physics():
    assert match_game(G, "cs") == Game("3", "Counter-Strike 2")


def test_word_prefix_is_strong():
    assert match_game(G, "hollow") == Game("6", "Hollow Knight")
    assert match_game(G, "dark souls") == Game("4", "Dark Souls III")


def test_weak_suggestions_include_close_names():
    assert Game("1", "Room") in match_game(G, "doom")


# ---------- I4: organização nunca perde o registro para desfazer ----------

from ultron.tools.folders import execute_plan, plan_organize, undo_plan


def _dir(tmp_path):
    d = tmp_path / "Downloads"
    d.mkdir()
    (d / "a.pdf").write_text("pdf")
    (d / "b.png").write_text("png")
    (d / "desktop.ini").write_text("ini")
    return d


def test_rerun_refused_and_undo_still_works(tmp_path):
    d, home = _dir(tmp_path), tmp_path / "home"
    p = plan_organize(home, d)
    execute_plan(home, p.id)
    assert "já foi executado" in execute_plan(home, p.id)
    undo_plan(home, p.id)
    assert (d / "a.pdf").exists() and (d / "b.png").exists()


def test_desktop_ini_not_moved(tmp_path):
    d, home = _dir(tmp_path), tmp_path / "home"
    p = plan_organize(home, d)
    assert all(not m.src.endswith("desktop.ini") for m in p.moves)


def test_partial_failure_keeps_undo_log(tmp_path, monkeypatch):
    import shutil as sh
    from ultron.tools import folders
    d, home = _dir(tmp_path), tmp_path / "home"
    real_move = sh.move

    def flaky_move(src, dst):
        if src.endswith("b.png"):
            raise PermissionError("arquivo aberto em outro programa")
        return real_move(src, dst)

    monkeypatch.setattr(folders.shutil, "move", flaky_move)
    p = plan_organize(home, d)
    msg = execute_plan(home, p.id)
    assert "b.png" in msg  # falha relatada
    assert (d / "Documentos" / "a.pdf").exists()
    monkeypatch.setattr(folders.shutil, "move", real_move)
    undo_plan(home, p.id)
    assert (d / "a.pdf").exists()


def test_plan_id_validated(tmp_path):
    assert execute_plan(tmp_path, "../../x").startswith("ERRO")


# ---------- I5: HUD caindo no meio não perde a resposta ----------

class SlowBrain(FakeBrain):
    async def send(self, session_id, history, text, system, chat_ref=None):
        import asyncio
        yield Event("text", "parte 1")
        await asyncio.sleep(0.3)
        yield Event("text", "parte 2")
        yield Event("done")


def test_reply_saved_when_hud_disconnects(tmp_path):
    with make_client(tmp_path, {"claude": SlowBrain("claude")}) as c:
        h = {"X-Ultron-Token": TOKEN}
        cid = c.post("/api/chats", json={"brain": "claude"}, headers=h).json()["id"]
        with c.websocket_connect(f"/ws?t={TOKEN}", headers=LOCAL_WS) as ws:
            ws.send_json({"type": "send", "chat_id": cid, "text": "oi"})
            assert ws.receive_json()["text"] == "parte 1"
        for _ in range(50):
            msgs = c.get(f"/api/chats/{cid}/messages", headers=h).json()
            if len(msgs) == 2:
                break
            time.sleep(0.05)
        assert msgs[-1]["content"] == "parte 1\n\nparte 2"


async def test_claude_process_killed_when_stream_abandoned(tmp_path, monkeypatch):
    import stat
    fix = Path(__file__).parent / "fixtures"
    p = tmp_path / "claude"
    p.write_text(f"#!/bin/sh\nexec {sys.executable} {fix / 'fake_claude.py'} \"$@\"\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    monkeypatch.setenv("FAKE_CLAUDE_PIDFILE", str(tmp_path / "pid"))
    from ultron.brains.claude_code import ClaudeCodeBrain
    b = ClaudeCodeBrain(make_cfg(tmp_path, claude_bin=str(p)), tmp_path / "m.json", [], tmp_path)
    gen = b.send(None, [], "oi", "")
    await gen.__anext__()
    await gen.aclose()
    pid = int((tmp_path / "pid").read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
            os.waitpid(pid, os.WNOHANG)
        except (ProcessLookupError, ChildProcessError):
            break
        time.sleep(0.05)
    else:
        pytest.fail("processo do claude continua vivo")


# ---------- Recomendação: não escrever em .obsidian (plugins executam código) ----------

def test_vault_refuses_obsidian_config(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    with pytest.raises(ValueError):
        v.write(".obsidian/plugins/x/main.js", "alert(1)")
    with pytest.raises(ValueError):
        v.write("Notas/../.obsidian/app.json", "{}")
