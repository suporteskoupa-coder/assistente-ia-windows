from datetime import datetime

import pytest

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.memory import Vault
from ultron.service import Ultron


@pytest.fixture
def env(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    brains = {"claude": FakeBrain("claude"), "ollama": FakeBrain("ollama")}
    u = Ultron(cfg, ChatStore(cfg.db_path), v, brains, ConfirmBroker(), now=lambda: datetime(2026, 10, 27, 22, 15))
    return u, brains, v


async def run(u, chat_id, text):
    return [e async for e in u.send(chat_id, text)]


async def test_send_flow(env):
    u, brains, v = env
    c = u.new_chat("claude")
    evs = await run(u, c.id, "avisa o pessoal que vou entrar no cs agora mesmo pessoal")
    assert [e.kind for e in evs] == ["session", "tool", "text", "text", "done"]
    chat = u.store.get(c.id)
    assert chat.title == "avisa o pessoal que vou entrar…"
    assert chat.claude_session_id == "s1"
    msgs = u.store.messages(c.id)
    assert [(m.role, m.content) for m in msgs] == [("user", "avisa o pessoal que vou entrar no cs agora mesmo pessoal"),
                                                    ("assistant", "Abrindo\n\no CS.")]
    diary = v.read("Ultron/Diario/2026-10-27.md")
    assert "22:15 [claude] [[Chat 1|" in diary and "· abrir_jogo nome=cs" in diary


async def test_second_message_resumes_session(env):
    u, brains, _ = env
    c = u.new_chat("claude")
    await run(u, c.id, "oi")
    await run(u, c.id, "de novo")
    assert brains["claude"].calls[1]["session_id"] == "s1"


async def test_system_has_memory_and_concluir_hint_only_for_claude(env):
    u, brains, v = env
    v.remember("Meu nome é Operador")
    await run(u, u.new_chat("claude").id, "oi")
    await run(u, u.new_chat("ollama").id, "oi")
    assert "Meu nome é Operador" in brains["claude"].calls[0]["system"]
    assert "concluir" in brains["claude"].calls[0]["system"]
    assert "concluir" not in brains["ollama"].calls[0]["system"]
    assert "Meu nome é Operador" in brains["ollama"].calls[0]["system"]


async def test_unknown_brain_rejected(env):
    u, _, _ = env
    with pytest.raises(ValueError):
        u.new_chat("gpt")


async def test_switch_brain_creates_continuation(env):
    u, brains, _ = env
    c = u.new_chat("claude")
    await run(u, c.id, "oi")
    new = await u.switch_brain(c.id, "ollama")
    assert new.brain == "ollama" and new.continues_from == c.id
    assert "resumo do chat" in u.store.messages(new.id)[0].content
    assert len(u.store.messages(c.id)) == 2  # resumo não entra no chat original


async def test_continuation_into_claude_gets_summary_in_system(env):
    u, brains, _ = env
    c = u.new_chat("ollama")
    await run(u, c.id, "oi")
    new = await u.switch_brain(c.id, "claude")
    await run(u, new.id, "continua")
    assert "resumo do chat" in brains["claude"].calls[-1]["system"]


async def test_close_chat_writes_summary(env):
    u, _, v = env
    c = u.new_chat("claude")
    await run(u, c.id, "fale sobre jogos")
    await u.close_chat(c.id)
    files = list((v.root / "Ultron" / "Chats").glob("*.md"))
    assert len(files) == 1 and "resumo do chat" in files[0].read_text(encoding="utf-8")


async def test_close_empty_chat_writes_nothing(env):
    u, _, v = env
    c = u.new_chat("claude")
    await u.close_chat(c.id)
    assert list((v.root / "Ultron" / "Chats").glob("*.md")) == []


async def test_title_with_bad_filename_chars(env):
    u, _, v = env
    c = u.new_chat("claude")
    await run(u, c.id, 'o que é C:\\temp/x? "a" <b>')
    await u.close_chat(c.id)
    assert len(list((v.root / "Ultron" / "Chats").glob("*.md"))) == 1
