"""Proveniência das conclusões: de quais chats cada uma veio."""
import json
from datetime import date

import httpx
import pytest

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.events import Event
from ultron.memory import Conclusion, Vault
from ultron.reflect import apply_reflection


@pytest.fixture
def vault(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    return v


def test_line_format_with_sources(vault):
    c = Conclusion("Joga à noite", "média", 2, "2026-10-27", ["#12 Noite de jogo", "#15 Abre o CS"])
    vault.save_conclusions([c])
    text = vault.read("Ultron/Memoria/conclusoes.md")
    assert "- Joga à noite · confiança: média · visto em 2 chats · 2026-10-27 · fontes: [[Chat 12|Noite de jogo]]; [[Chat 15|Abre o CS]]" in text
    assert vault.conclusions() == [c]


def test_legacy_line_without_sources_still_parses(vault):
    vault.write("Ultron/Memoria/conclusoes.md", "# C\n\n- Velha · confiança: alta · visto em 3 chats · 2026-10-01\n")
    assert vault.conclusions() == [Conclusion("Velha", "alta", 3, "2026-10-01", [])]


def test_same_chat_does_not_increment(vault):
    vault.conclude("Joga à noite", "baixa", "2026-10-27", source="#12 Noite de jogo")
    c = vault.conclude("Joga à noite", "média", "2026-10-27", source="#12 Noite de jogo")
    assert c.seen == 1 and c.sources == ["#12 Noite de jogo"] and c.confidence == "média"


def test_different_chats_increment(vault):
    vault.conclude("Joga à noite", "baixa", "2026-10-26", source="#12 Noite de jogo")
    c = vault.conclude("Joga à noite", "média", "2026-10-27", source="#15 Abre o CS")
    assert c.seen == 2 and c.sources == ["#12 Noite de jogo", "#15 Abre o CS"]


def test_same_chat_id_with_new_title_is_same_chat(vault):
    vault.conclude("X", "baixa", "2026-10-27", source="#12 Novo chat")
    c = vault.conclude("X", "baixa", "2026-10-27", source="#12 Noite de jogo")
    assert c.seen == 1


def test_bad_chars_in_title_do_not_break_format(vault):
    vault.conclude("X", "alta", "2026-10-27", source="#3 a · b; c")
    vault.conclude("X", "alta", "2026-10-27", source="#4 d")
    assert vault.conclusions()[0].seen == 2


def test_context_needs_two_chats(vault):
    vault.conclude("Um chat só", "alta", "2026-10-27", source="#1 a")
    vault.conclude("Dois chats", "média", "2026-10-27", source="#1 a")
    vault.conclude("Dois chats", "média", "2026-10-27", source="#2 b")
    ctx = vault.fixed_context()
    assert "Dois chats" in ctx and "Um chat só" not in ctx
    assert "[[Chat 1|a]]; [[Chat 2|b]]" in ctx  # fontes vão junto, para ele poder explicar


def test_legacy_without_sources_not_in_context(vault):
    vault.save_conclusions([Conclusion("Velha", "alta", 5, "2026-10-01", [])])
    assert "Velha" not in vault.fixed_context()


async def test_concluir_tool_records_chat_source(tmp_path):
    from ultron.tools.registry import build_registry
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    reg = build_registry(cfg, v, lambda t: None, httpx.AsyncClient(), chat_source="#7 Teste")
    await reg.call("concluir", {"texto": "Gosta de CS", "confianca": "baixa"})
    assert v.conclusions()[0].sources == ["#7 Teste"]


def test_mcp_config_per_chat(tmp_path):
    from ultron.brains.claude_code import mcp_config_for
    base = tmp_path / "mcp.json"
    base.write_text(json.dumps({"mcpServers": {"ultron": {"command": "py", "env": {"ULTRON_TOKEN": "t"}}}}))
    p = mcp_config_for(base, "#12 Noite de jogo", tmp_path / "out")
    env = json.loads(p.read_text())["mcpServers"]["ultron"]["env"]
    assert env == {"ULTRON_TOKEN": "t", "ULTRON_CHAT": "#12 Noite de jogo"}
    assert json.loads(base.read_text())["mcpServers"]["ultron"]["env"] == {"ULTRON_TOKEN": "t"}
    assert mcp_config_for(base, "#12 Noite de jogo", tmp_path / "out") == p
    assert mcp_config_for(base, None, tmp_path / "out") == base


async def test_claude_brain_uses_per_chat_config(tmp_path, monkeypatch):
    from ultron.brains import claude_code
    seen = {}

    async def fake_exec(*a, **kw):
        seen["args"] = a
        raise OSError("parar")

    base = tmp_path / "mcp.json"
    base.write_text(json.dumps({"mcpServers": {"ultron": {"command": "py", "env": {}}}}))
    monkeypatch.setattr(claude_code.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(claude_code.shutil, "which", lambda b: "/bin/claude")
    b = claude_code.ClaudeCodeBrain(make_cfg(tmp_path), base, [], tmp_path)
    [e async for e in b.send(None, [], "oi", "", chat_ref="#3 x")]
    cfg_path = seen["args"][seen["args"].index("--mcp-config") + 1]
    assert json.loads(open(cfg_path).read())["mcpServers"]["ultron"]["env"]["ULTRON_CHAT"] == "#3 x"


async def test_service_passes_chat_ref(tmp_path):
    from ultron.chats import ChatStore
    from ultron.confirm import ConfirmBroker
    from ultron.service import Ultron
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    b = FakeBrain("claude")
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": b}, ConfirmBroker())
    c = u.new_chat("claude")
    [e async for e in u.send(c.id, "noite de jogo")]
    assert b.calls[0]["chat_ref"] == f"#{c.id} noite de jogo"


def test_reflection_keeps_sources_when_model_drops_them():
    cur = [Conclusion("Joga à noite", "média", 2, "2026-10-20", ["#1 a", "#2 b"])]
    reply = "<conclusoes>\n- Joga à noite · confiança: alta · visto em 2 chats · 2026-10-27\n</conclusoes>"
    out = apply_reflection(cur, reply, date(2026, 10, 27))
    assert out[0].sources == ["#1 a", "#2 b"] and out[0].confidence == "alta"


def test_reflection_old_single_source_removed():
    cur = [Conclusion("velha", "baixa", 1, "2026-09-01", ["#1 a"])]
    reply = "<conclusoes>\n" + cur[0].line() + "\n</conclusoes>"
    assert apply_reflection(cur, reply, date(2026, 10, 27)) == []
