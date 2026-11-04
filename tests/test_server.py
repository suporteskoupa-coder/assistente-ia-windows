import threading
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.memory import Vault
from ultron.server import create_app
from ultron.service import Ultron


@pytest.fixture
def client(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    hud = tmp_path / "hud"
    hud.mkdir()
    (hud / "index.html").write_text("<h1>ULTRON</h1>")
    broker = ConfirmBroker(timeout=5)
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain("claude"), "ollama": FakeBrain("ollama")}, broker)
    with TestClient(create_app(u, broker, hud)) as c:
        c.broker = broker
        yield c


def test_hud_served(client):
    assert "ULTRON" in client.get("/").text


def test_chat_crud(client):
    r = client.post("/api/chats", json={"brain": "claude"})
    cid = r.json()["id"]
    assert client.get("/api/chats").json()[0]["id"] == cid
    assert client.get(f"/api/chats/{cid}/messages").json() == []
    assert client.post("/api/chats", json={"brain": "gpt"}).status_code == 400
    assert client.get("/api/chats/999/messages").status_code == 404


def test_ws_send_streams_events(client):
    cid = client.post("/api/chats", json={"brain": "claude"}).json()["id"]
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "send", "chat_id": cid, "text": "oi"})
        kinds = []
        while True:
            m = ws.receive_json()
            assert m["chat_id"] == cid
            kinds.append(m["type"])
            if m["type"] in ("done", "error"):
                break
    assert kinds == ["session", "tool", "text", "text", "done"]
    assert len(client.get(f"/api/chats/{cid}/messages").json()) == 2


def test_permission_resolved_by_confirm_and_pushed_to_ws(client):
    result = {}
    with client.websocket_connect("/ws") as ws:
        def ask():
            result["r"] = client.post("/api/permission", json={
                "tool_name": "mcp__ultron__discord_enviar", "input": {"canal": "geral", "texto": "oi"}}).json()
        t = threading.Thread(target=ask)
        t.start()
        m = ws.receive_json()
        assert m["type"] == "confirm" and m["action"] == "discord_enviar"
        assert m["detail"] == {"canal": "geral", "texto": "oi"}
        client.post(f"/api/confirm/{m['id']}", json={"allow": True, "edited": {"canal": "geral", "texto": "olá"}})
        t.join(5)
    assert result["r"] == {"allow": True, "input": {"canal": "geral", "texto": "olá"}}


def test_permission_denied(client):
    result = {}
    with client.websocket_connect("/ws") as ws:
        t = threading.Thread(target=lambda: result.setdefault("r", client.post(
            "/api/permission", json={"tool_name": "Bash", "input": {"command": "dir"}}).json()))
        t.start()
        m = ws.receive_json()
        assert m["action"] == "Bash"
        client.post(f"/api/confirm/{m['id']}", json={"allow": False})
        t.join(5)
    assert result["r"]["allow"] is False


def test_status(client):
    s = client.get("/api/status").json()
    assert set(s) >= {"notes", "actions_today", "games", "ollama", "claude"}


def test_switch_and_close(client):
    cid = client.post("/api/chats", json={"brain": "claude"}).json()["id"]
    new = client.post(f"/api/chats/{cid}/switch", json={"brain": "ollama"}).json()
    assert new["brain"] == "ollama" and new["continues_from"] == cid
    assert client.post(f"/api/chats/{cid}/close").status_code == 200


def test_conclusions_endpoint(client):
    assert client.get("/api/conclusions").json() == []
