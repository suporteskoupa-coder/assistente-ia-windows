"""Ler a tela: captura, servidor, MCP e cérebro local."""
import base64
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.memory import Vault
from ultron.screen import MAX_SIDE, ScreenCapturer
from ultron.server import create_app
from ultron.service import Ultron


def fake_grab(size=(3000, 2000)):
    return lambda: Image.new("RGB", size, (200, 30, 30))


def decode(b64):
    return Image.open(io.BytesIO(base64.b64decode(b64)))


# ---------- captura ----------

async def test_capture_downscales_to_max_side():
    shot = await ScreenCapturer(grab=fake_grab()).capture()
    img = decode(shot.png_b64)
    assert img.format == "PNG" and max(img.size) == MAX_SIDE
    assert (shot.width, shot.height) == img.size


async def test_small_screen_not_upscaled():
    shot = await ScreenCapturer(grab=fake_grab((800, 600))).capture()
    assert (shot.width, shot.height) == (800, 600)


async def test_window_hidden_during_capture_and_restored_on_error():
    order = []

    def grab():
        order.append("grab")
        raise OSError("sem tela")

    cap = ScreenCapturer(grab=grab, delay=0)
    cap.set_window_hooks(lambda: order.append("hide"), lambda: order.append("show"))
    with pytest.raises(OSError):
        await cap.capture()
    assert order == ["hide", "grab", "show"]


# ---------- servidor ----------

def client(tmp_path, enabled=True, grab=None):
    cfg = make_cfg(tmp_path, screen_enabled=enabled)
    v = Vault(cfg.vault)
    v.ensure()
    hud = tmp_path / "hud"
    hud.mkdir(exist_ok=True)
    (hud / "index.html").write_text("x")
    broker = ConfirmBroker()
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain()}, broker)
    cap = ScreenCapturer(grab=grab or fake_grab(), delay=0)
    return TestClient(create_app(u, broker, hud, capturer=cap)), v


def test_screenshot_endpoint(tmp_path):
    c, v = client(tmp_path)
    with c:
        r = c.post("/api/screenshot").json()
    assert decode(r["png_b64"]).size == (r["width"], r["height"])
    assert "ver_tela" in "".join(p.read_text(encoding="utf-8") for p in (v.root / "Ultron" / "Diario").glob("*.md"))


def test_screenshot_disabled(tmp_path):
    c, _ = client(tmp_path, enabled=False)
    with c:
        r = c.post("/api/screenshot")
    assert r.status_code == 403 and "desligada" in r.json()["detail"]


def test_screenshot_capture_error(tmp_path):
    def bad():
        raise OSError("sem monitor")
    c, _ = client(tmp_path, grab=bad)
    with c:
        r = c.post("/api/screenshot")
    assert r.status_code == 500 and "sem monitor" in r.json()["detail"]


# ---------- MCP (cérebro Claude) ----------

def mcp(tmp_path, handler):
    from ultron.mcp_server import McpServer
    from ultron.tools.registry import build_registry
    cfg = make_cfg(tmp_path)
    reg = build_registry(cfg, Vault(cfg.vault), lambda t: None, httpx.AsyncClient())
    return McpServer(reg, "http://core", httpx.AsyncClient(transport=httpx.MockTransport(handler)), token="tk")


async def test_mcp_lists_ver_tela(tmp_path):
    s = mcp(tmp_path, lambda r: httpx.Response(200))
    r = await s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "ver_tela" in {t["name"] for t in r["result"]["tools"]}


async def test_mcp_ver_tela_returns_image(tmp_path):
    seen = []

    def h(req):
        seen.append((req.url.path, req.headers.get("X-Ultron-Token")))
        return httpx.Response(200, json={"png_b64": "QUJD", "width": 10, "height": 5})

    r = await mcp(tmp_path, h).handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                       "params": {"name": "ver_tela", "arguments": {}}})
    content = r["result"]["content"]
    assert content[0] == {"type": "image", "data": "QUJD", "mimeType": "image/png"}
    assert "10x5" in content[1]["text"]
    assert r["result"]["isError"] is False
    assert seen == [("/api/screenshot", "tk")]


async def test_mcp_ver_tela_error_is_text(tmp_path):
    r = await mcp(tmp_path, lambda q: httpx.Response(403, json={"detail": "Leitura de tela desligada"})).handle(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ver_tela", "arguments": {}}})
    assert r["result"]["isError"] is True and "desligada" in r["result"]["content"][0]["text"]


def test_ver_tela_allowed_without_confirmation(tmp_path):
    from ultron.app import build_allowed
    from ultron.tools.registry import build_registry
    cfg = make_cfg(tmp_path)
    reg = build_registry(cfg, Vault(cfg.vault), lambda t: None, httpx.AsyncClient())
    assert "mcp__ultron__ver_tela" in build_allowed(reg, cfg)


# ---------- cérebro local ----------

def ollama_setup(tmp_path, responses, vision="qwen3-vl:8b", enabled=True):
    from ultron.brains.ollama import OllamaBrain
    from ultron.tools.registry import build_registry
    cfg = make_cfg(tmp_path, ollama_vision_model=vision, screen_enabled=enabled)
    v = Vault(cfg.vault)
    v.ensure()
    reg = build_registry(cfg, v, lambda t: None, httpx.AsyncClient())
    sent = []
    it = iter(responses)

    def h(req):
        sent.append(json.loads(req.content))
        return next(it)

    b = OllamaBrain(cfg, reg, ConfirmBroker(timeout=0.05), httpx.AsyncClient(transport=httpx.MockTransport(h)),
                    capturer=ScreenCapturer(grab=fake_grab((100, 50)), delay=0))
    return b, sent


def reply(content="", calls=None):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [{"function": {"name": n, "arguments": a}} for n, a in calls]
    return httpx.Response(200, json={"message": msg})


async def test_local_ver_tela_uses_vision_model(tmp_path):
    b, sent = ollama_setup(tmp_path, [
        reply(calls=[("ver_tela", {"pergunta": "qual o erro?"})]),
        reply("A tela mostra: ERRO 0x80070005"),
        reply("É um erro de permissão."),
    ])
    evs = [e async for e in b.send(None, [], "o que é esse erro na tela?", "sys")]
    assert [e.kind for e in evs] == ["tool", "text", "done"]
    vision_call = sent[1]
    assert vision_call["model"] == "qwen3-vl:8b"
    assert vision_call["messages"][0]["images"] and "qual o erro?" in vision_call["messages"][0]["content"]
    assert "tools" not in vision_call
    assert "ERRO 0x80070005" in sent[2]["messages"][-1]["content"]
    assert sent[2]["model"] == "m"


async def test_local_ver_tela_offered_only_when_configured(tmp_path):
    b, sent = ollama_setup(tmp_path, [reply("x")], vision=None)
    [e async for e in b.send(None, [], "oi", "sys")]
    assert "ver_tela" not in {t["function"]["name"] for t in sent[0]["tools"]}
    b, sent = ollama_setup(tmp_path, [reply("x")], enabled=False)
    [e async for e in b.send(None, [], "oi", "sys")]
    assert "ver_tela" not in {t["function"]["name"] for t in sent[0]["tools"]}


async def test_local_vision_model_missing(tmp_path):
    b, sent = ollama_setup(tmp_path, [
        reply(calls=[("ver_tela", {"pergunta": "?"})]),
        httpx.Response(404, json={"error": "model not found"}),
        reply("não consegui"),
    ])
    [e async for e in b.send(None, [], "olha a tela", "sys")]
    assert "ollama pull qwen3-vl:8b" in sent[2]["messages"][-1]["content"]


# ---------- configuração e prompt ----------

def test_config_screen_defaults(tmp_path):
    from ultron.config import load_config
    p = tmp_path / "u.toml"
    p.write_text("")
    cfg = load_config(p)
    assert cfg.screen_enabled is True and cfg.ollama_vision_model == "qwen3-vl:8b"
    p.write_text('[tela]\nhabilitada = false\n[ollama]\nvision_model = ""\n')
    cfg = load_config(p)
    assert cfg.screen_enabled is False and cfg.ollama_vision_model is None


async def test_prompt_says_only_when_asked(tmp_path):
    c, _ = client(tmp_path)
    u = c.app.state.ultron
    chat = u.new_chat("claude")
    assert "ver_tela" in u.system_prompt(chat) and "pedir" in u.system_prompt(chat)
