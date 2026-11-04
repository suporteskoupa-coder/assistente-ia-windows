"""Modo atual do Ultron (CLAUDE/LOCAL) e quem responde no servidor."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.memory import Vault
from ultron.server import create_app
from ultron.server_replies import ModeStore, make_mode_ask, make_ollama_ask, strip_thinking
from ultron.service import Ultron


def test_mode_store_default_and_persist(tmp_path):
    m = ModeStore(tmp_path / "mode.json")
    assert m.get() == "claude"
    m.set("ollama")
    assert ModeStore(tmp_path / "mode.json").get() == "ollama"
    with pytest.raises(ValueError):
        m.set("gpt")


def test_mode_api(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    hud = tmp_path / "hud"
    hud.mkdir()
    (hud / "index.html").write_text("x")
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain(), "ollama": FakeBrain("ollama")}, ConfirmBroker())
    mode = ModeStore(cfg.home / "mode.json")
    with TestClient(create_app(u, ConfirmBroker(), hud, mode=mode)) as c:
        assert c.get("/api/mode").json() == {"brain": "claude"}
        assert c.post("/api/mode", json={"brain": "ollama"}).json() == {"brain": "ollama"}
        assert c.post("/api/mode", json={"brain": "gpt"}).status_code == 400
    assert mode.get() == "ollama"


class Ask:
    def __init__(self, name, fail=False):
        self.name, self.fail, self.calls = name, fail, 0

    async def __call__(self, system, text):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} falhou")
        return f"resposta do {self.name}"


@pytest.mark.parametrize("setting,mode,expected", [
    ("seguir", "claude", "resposta do claude"),
    ("seguir", "ollama", "resposta do local"),
    ("claude", "ollama", "resposta do claude"),
    ("local", "claude", "resposta do local"),
])
async def test_mode_ask_picks_brain(tmp_path, setting, mode, expected):
    m = ModeStore(tmp_path / "m.json")
    m.set(mode)
    ask = make_mode_ask(setting, m, Ask("claude"), Ask("local"))
    assert await ask("s", "t") == expected


async def test_claude_failure_falls_back_to_local(tmp_path):
    m = ModeStore(tmp_path / "m.json")
    claude, local = Ask("claude", fail=True), Ask("local")
    assert await make_mode_ask("seguir", m, claude, local)("s", "t") == "resposta do local"


async def test_local_failure_does_not_spend_claude(tmp_path):
    m = ModeStore(tmp_path / "m.json")
    m.set("ollama")
    claude, local = Ask("claude"), Ask("local", fail=True)
    with pytest.raises(RuntimeError):
        await make_mode_ask("seguir", m, claude, local)("s", "t")
    assert claude.calls == 0


@pytest.mark.parametrize("raw,clean", [
    ("<think>vou pensar no usuario</think>Ele entra às 21h.", "Ele entra às 21h."),
    ("<think>\nlinha\nlinha\n</think>\n\nOk.", "Ok."),
    ("<think>pensamento sem fim", ""),
    ("Resposta normal.", "Resposta normal."),
])
def test_strip_thinking(raw, clean):
    assert strip_thinking(raw) == clean


async def test_ollama_ask_strips_thinking(tmp_path):
    cfg = make_cfg(tmp_path)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, json={"message": {"content": "<think>hmm</think>Deve entrar."}})))
    assert await make_ollama_ask(cfg, http)("s", "t") == "Deve entrar."


def test_config_server_brain_default_seguir(tmp_path):
    from ultron.config import load_config
    p = tmp_path / "u.toml"
    p.write_text("")
    assert load_config(p).server_brain == "seguir"
