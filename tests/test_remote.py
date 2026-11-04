"""Controle pelo celular via DM do Discord."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.events import Event
from ultron.memory import Vault
from ultron.remote import REMOTE_TITLE, RemoteControl, split_message
from ultron.server import create_app
from ultron.service import Ultron

OWNER = 111


def setup(tmp_path, brain=None, timeout=5):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    broker = ConfirmBroker(timeout=timeout)
    b = brain or FakeBrain("claude", script=[Event("text", "Pronto."), Event("done")])
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": b}, broker)
    sent = []

    async def send(text):
        sent.append(text)

    return RemoteControl(u, broker, OWNER, send), u, b, sent, broker, v


async def test_ignores_strangers(tmp_path):
    rc, u, b, sent, _, _ = setup(tmp_path)
    await rc.on_dm(999, "abre o cs")
    assert sent == [] and b.calls == [] and u.store.list() == []


async def test_owner_message_answered_in_fixed_chat(tmp_path):
    rc, u, b, sent, _, v = setup(tmp_path)
    await rc.on_dm(OWNER, "quais minhas pendências?")
    await rc.on_dm(OWNER, "e agora?")
    assert sent == ["Pronto.", "Pronto."]
    chats = u.store.list()
    assert len(chats) == 1 and chats[0].title == REMOTE_TITLE
    assert "[celular] quais minhas pendências?" in "".join(p.read_text(encoding="utf-8") for p in (v.root / "Ultron" / "Diario").glob("*.md"))


async def test_error_event_is_reported(tmp_path):
    rc, _, _, sent, _, _ = setup(tmp_path, FakeBrain("claude", script=[Event("error", "Limite atingido")]))
    await rc.on_dm(OWNER, "oi")
    assert sent and "Limite atingido" in sent[-1]


def test_split_message():
    parts = split_message("a" * 4500)
    assert [len(p) for p in parts] == [2000, 2000, 500]
    parts = split_message(("linha\n" * 500).strip())
    assert all(len(p) <= 2000 for p in parts) and "".join(parts).count("linha") == 500
    assert split_message("") == ["(sem resposta)"]


async def test_busy_while_answering(tmp_path):
    class Slow(FakeBrain):
        async def send(self, *a, **kw):
            await asyncio.sleep(0.2)
            yield Event("text", "ok")
            yield Event("done")

    rc, _, _, sent, _, _ = setup(tmp_path, Slow("claude"))
    await asyncio.gather(rc.on_dm(OWNER, "um"), asyncio.sleep(0.05))
    t = asyncio.create_task(rc.on_dm(OWNER, "um"))
    await asyncio.sleep(0.05)
    await rc.on_dm(OWNER, "dois")
    await t
    assert any("ainda" in s.lower() for s in sent)


async def test_remote_confirmation_yes_and_no(tmp_path):
    rc, _, _, sent, broker, _ = setup(tmp_path)
    rc.start()
    task = asyncio.create_task(broker.request_detail("discord_enviar", {"canal": "geral", "texto": "oi"}, meta={"remote": True}))
    for _ in range(100):
        if any("sim" in s for s in sent):
            break
        await asyncio.sleep(0.01)
    assert "#geral" in sent[-1] and '"oi"' in sent[-1]
    await rc.on_dm(OWNER, "Sim")
    assert (await task)[0] is True

    task = asyncio.create_task(broker.request_detail("organizar_pasta", {"plano_id": "abcd1234"}, meta={"remote": True}))
    for _ in range(100):
        if rc.pending_confirm:
            break
        await asyncio.sleep(0.01)
    await rc.on_dm(OWNER, "olha outra coisa")
    assert "sim ou não" in sent[-1].lower()
    await rc.on_dm(OWNER, "não")
    assert (await task)[0] is False
    rc.stop()


async def test_local_confirmations_not_sent_to_phone(tmp_path):
    rc, _, _, sent, broker, _ = setup(tmp_path, timeout=0.05)
    rc.start()
    await broker.request_detail("discord_enviar", {"canal": "geral", "texto": "oi"})
    await asyncio.sleep(0.02)
    assert sent == []
    rc.stop()


# ---------- permissões de pedidos vindos do celular ----------

def app_client(tmp_path, rc_setup):
    rc, u, _, _, broker, _ = rc_setup
    hud = tmp_path / "hud"
    hud.mkdir(exist_ok=True)
    (hud / "index.html").write_text("x")
    return TestClient(create_app(u, broker, hud, remote=rc))


def test_native_tools_denied_for_remote_chat(tmp_path):
    s = setup(tmp_path)
    rc, u = s[0], s[1]
    chat = rc.chat()
    with app_client(tmp_path, s) as c:
        for tool in ("Bash", "Write", "Edit", "NotebookEdit"):
            r = c.post("/api/permission", json={"tool_name": tool, "input": {"command": "del *"},
                                                "chat": f"#{chat.id} {REMOTE_TITLE}"}).json()
            assert r["allow"] is False
    assert s[4].pending() == []


def test_ultron_tools_from_remote_marked_remote(tmp_path):
    s = setup(tmp_path, timeout=0.2)
    rc, broker = s[0], s[4]
    chat = rc.chat()
    q = broker.subscribe()
    with app_client(tmp_path, s) as c:
        c.post("/api/permission", json={"tool_name": "mcp__ultron__discord_enviar", "input": {"canal": "geral", "texto": "x"},
                                        "chat": f"#{chat.id} {REMOTE_TITLE}"})
    item = q.get_nowait()
    assert item["remote"] is True and item["action"] == "discord_enviar"


def test_local_chat_permission_unchanged(tmp_path):
    s = setup(tmp_path, timeout=0.2)
    broker = s[4]
    q = broker.subscribe()
    with app_client(tmp_path, s) as c:
        c.post("/api/permission", json={"tool_name": "Bash", "input": {"command": "dir"}, "chat": "#99 Outro"})
    item = q.get_nowait()
    assert item["action"] == "Bash" and not item.get("remote")


async def test_mcp_permission_sends_chat(tmp_path, monkeypatch):
    from ultron.mcp_server import McpServer
    from ultron.tools.registry import build_registry
    cfg = make_cfg(tmp_path)
    seen = []

    def h(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"allow": False})

    monkeypatch.setenv("ULTRON_CHAT", "#5 Discord (celular)")
    reg = build_registry(cfg, Vault(cfg.vault), lambda t: None, httpx.AsyncClient())
    s = McpServer(reg, "http://core", httpx.AsyncClient(transport=httpx.MockTransport(h)), token="t")
    await s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "aprovar_permissao", "arguments": {"tool_name": "Bash", "input": {}}}})
    assert seen[0]["chat"] == "#5 Discord (celular)"


async def test_remote_prompt_restrictions(tmp_path):
    rc, u, _, _, _, _ = setup(tmp_path)
    p = u.system_prompt(rc.chat())
    assert "celular" in p and "bloqueado" in p


# ---------- configuração ----------

def test_config_remote(tmp_path):
    from ultron.config import load_config
    p = tmp_path / "u.toml"
    p.write_text("")
    cfg = load_config(p)
    assert cfg.remote_enabled is False and cfg.discord_owner_id is None and cfg.reminders_to_phone is False
    p.write_text('[discord]\ncontrole_remoto = true\ndono_id = "123"\nlembretes_no_celular = true\n')
    cfg = load_config(p)
    assert cfg.remote_enabled and cfg.discord_owner_id == 123 and cfg.reminders_to_phone


def test_remote_requires_owner_and_token(tmp_path):
    from ultron.remote import remote_problem
    assert remote_problem(make_cfg(tmp_path, remote_enabled=False)) == "desligado"
    assert "dono_id" in remote_problem(make_cfg(tmp_path, remote_enabled=True, discord_owner_id=None))
    assert "token" in remote_problem(make_cfg(tmp_path, remote_enabled=True, discord_owner_id=1, discord_token=None))
    assert remote_problem(make_cfg(tmp_path, remote_enabled=True, discord_owner_id=1)) is None


# ---------- montagem no app ----------

def _cfg_file(tmp_path, extra=""):
    p = tmp_path / "u.toml"
    p.write_text(f'[paths]\nhome = "{(tmp_path / "home").as_posix()}"\n' + extra, encoding="utf-8")
    return p


def test_app_without_remote(tmp_path, monkeypatch):
    from ultron.app import build
    monkeypatch.delenv("ULTRON_DISCORD_TOKEN", raising=False)
    _, app = build(_cfg_file(tmp_path), "t")
    assert app.state.remote is None


def test_app_with_remote_builds_bot(tmp_path, monkeypatch):
    from ultron.app import build
    monkeypatch.setenv("ULTRON_DISCORD_TOKEN", "tok")
    _, app = build(_cfg_file(tmp_path, '[discord]\ncontrole_remoto = true\ndono_id = "42"\n'), "t")
    assert app.state.remote is not None and app.state.remote.owner_id == 42
    assert app.state.discord_client.intents.dm_messages is True
    assert app.state.discord_client.intents.message_content is False


async def test_reminder_goes_to_phone_when_enabled(tmp_path):
    from datetime import datetime, timedelta
    from ultron.app import phone_notifier
    sent, win = [], []

    async def send(t):
        sent.append(t)

    notify = phone_notifier(send, lambda a, b: win.append(b))
    notify("Ultron · lembrete", "pizza")
    await asyncio.sleep(0.01)
    assert sent == ["⏰ pizza"] and win == ["pizza"]

    def broken(a, b):
        raise OSError("sem toast")

    notify = phone_notifier(send, broken)
    with pytest.raises(OSError):
        notify("Ultron · lembrete", "remédio")
    await asyncio.sleep(0.01)
    assert sent[-1] == "⏰ remédio"  # celular recebe mesmo se a notificação do Windows falhar


async def test_handle_returns_reply_text(tmp_path):
    rc, _, b, sent, _, _ = setup(tmp_path)
    assert await rc.handle("oi") == "Pronto."
    assert sent == []  # handle não manda DM; quem chama decide onde responder


async def test_handle_ignores_none_when_busy(tmp_path):
    class Slow(FakeBrain):
        async def send(self, *a, **kw):
            await asyncio.sleep(0.2)
            yield Event("text", "ok")
            yield Event("done")

    rc, *_ = setup(tmp_path, Slow("claude"))
    t = asyncio.create_task(rc.handle("um"))
    await asyncio.sleep(0.05)
    assert "ainda" in (await rc.handle("dois")).lower()
    await t


# ---------- o Discord do criador segue o modo CLAUDE/LOCAL ----------

class _Mode:
    def __init__(self, brain):
        self.brain = brain

    def get(self):
        return self.brain


def setup_two_brains(tmp_path, mode):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    broker = ConfirmBroker(timeout=5)
    claude = FakeBrain("claude", script=[Event("text", "claude aqui"), Event("done")])
    local = FakeBrain("ollama", script=[Event("text", "qwen aqui"), Event("done")])
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": claude, "ollama": local}, broker)
    sent = []

    async def send(t):
        sent.append(t)

    return RemoteControl(u, broker, OWNER, send, mode=mode), u, claude, local, sent


async def test_remote_follows_local_mode(tmp_path):
    mode = _Mode("ollama")
    rc, u, claude, local, sent = setup_two_brains(tmp_path, mode)
    await rc.on_dm(OWNER, "oi")
    assert sent == ["qwen aqui"] and claude.calls == [] and len(local.calls) == 1
    mode.brain = "claude"
    await rc.on_dm(OWNER, "oi de novo")
    assert sent[-1] == "claude aqui"
    titles = sorted(c.title for c in u.store.list())
    assert len(titles) == 2 and all(t.startswith(REMOTE_TITLE) for t in titles)


async def test_both_remote_chats_are_recognized(tmp_path):
    mode = _Mode("ollama")
    rc, u, *_ = setup_two_brains(tmp_path, mode)
    local_chat = rc.chat()
    mode.brain = "claude"
    claude_chat = rc.chat()
    assert local_chat.id != claude_chat.id
    assert rc.is_remote_chat(f"#{local_chat.id} x") and rc.is_remote_chat(f"#{claude_chat.id} x")
    assert "celular" in u.system_prompt(local_chat)


async def test_local_brain_confirmation_goes_to_phone(tmp_path):
    import httpx
    from ultron.brains.ollama import OllamaBrain
    from ultron.tools.registry import build_registry
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    broker = ConfirmBroker(timeout=0.2)
    q = broker.subscribe()
    reg = build_registry(cfg, v, lambda t: None, httpx.AsyncClient())
    replies = iter([
        httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "discord_enviar", "arguments": {"canal": "geral", "texto": "x"}}}]}}),
        httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}}),
    ])
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: next(replies)))
    b = OllamaBrain(cfg, reg, broker, http)
    [e async for e in b.send(None, [], "manda x", "sys", chat_ref=f"#5 {REMOTE_TITLE} · local")]
    assert q.get_nowait()["remote"] is True
