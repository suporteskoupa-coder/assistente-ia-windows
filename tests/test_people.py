"""O Ultron sabe quem está falando no Discord e lembra de cada pessoa."""
from datetime import datetime, timedelta

import pytest

from tests.tools.helpers import make_cfg
from ultron.memory import Vault
from ultron.people import PeopleStore
from ultron.reminders import ReminderStore
from ultron.server_replies import ServerResponder, StatusStore

NOW = datetime(2026, 10, 27, 18, 43)


def test_person_note_created_and_updated(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    p = PeopleStore(v)
    p.record(111, "Amigo", "ultron o usuario vai entrar?", "Deve entrar às 21h.", NOW)
    p.record(111, "Amiguinho", "e amanhã?", "Não sei.", NOW + timedelta(minutes=1))
    text = v.read("Ultron/Pessoas/Amigo (111).md")
    assert "Amigo" in text and "Amiguinho" in text
    assert "o usuario vai entrar?" in text and "Deve entrar às 21h." in text
    assert p.context(111).count("→") == 2


def test_person_note_keeps_last_20(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    p = PeopleStore(v)
    for i in range(30):
        p.record(5, "Visitante", f"pergunta {i}", f"resposta {i}", NOW + timedelta(minutes=i))
    ctx = p.context(5)
    assert "pergunta 29" in ctx and "pergunta 9" not in ctx


def test_user_notes_about_person_are_kept(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    p = PeopleStore(v)
    p.record(7, "Colega", "oi", "oi", NOW)
    note = v.read("Ultron/Pessoas/Colega (7).md").replace("## Sobre", "## Sobre\n- melhor amigo do Usuario, joga de suporte")
    v.write("Ultron/Pessoas/Colega (7).md", note)
    p.record(7, "Colega", "tudo bem?", "tudo", NOW)
    assert "joga de suporte" in p.context(7)


def responder(tmp_path, **kw):
    cfg = make_cfg(tmp_path, server_enabled=True, server_channels=["10"], owner_name="Usuario",
                   discord_owner_id=42, server_notes="nenhuma", **kw)
    v = Vault(cfg.vault)
    v.ensure()
    calls = []

    async def ask(system, text):
        calls.append((system, text))
        return "resposta"

    r = ServerResponder(cfg, v, ReminderStore(cfg.db_path), StatusStore(cfg.home / "status.json"), ask, now=lambda: NOW)
    return r, calls, v


async def test_friend_memory_used_next_time(tmp_path):
    r, calls, v = responder(tmp_path)
    await r.on_message("10", "Amigo", False, "ultron, meu time é o Corinthians", author_id=111)
    await r.on_message("10", "Amigo", False, "ultron, qual meu time?", author_id=111)
    system = calls[1][0]
    assert "Corinthians" in system and "111" in system
    assert v.read("Ultron/Pessoas/Amigo (111).md")


async def test_other_people_notes_not_shown(tmp_path):
    r, calls, v = responder(tmp_path)
    await r.on_message("10", "Amigo", False, "ultron, segredo do Amigo: medo de altura", author_id=111)
    await r.on_message("10", "Visitante", False, "ultron, oi", author_id=222)
    assert "medo de altura" not in calls[1][0].split("# Conversa recente no canal")[0]


async def test_recent_channel_conversation_in_context(tmp_path):
    r, calls, v = responder(tmp_path)
    await r.on_message("10", "Amigo", False, "ultron, vamos jogar CS às 21h?", author_id=111)
    await r.on_message("10", "Visitante", False, "ultron, que horas ele disse?", author_id=222)
    assert "vamos jogar CS às 21h?" in calls[1][0]


async def test_owner_message_tells_main_brain_who_speaks(tmp_path):
    r, calls, v = responder(tmp_path)
    got = []

    async def handler(text, note):
        got.append(note + text)
        return "ok"

    r.owner_handler = handler
    await r.on_message("10", "Membro", False, "Ultron, quem sou eu?", author_id=42)
    assert "Membro" in got[0] and "criador" in got[0] and "Ultron, quem sou eu?" in got[0]


async def test_owner_identity_goes_in_system_not_user_text(tmp_path):
    r, calls, v = responder(tmp_path)
    got = []

    async def handler(text, note):
        got.append((text, note))
        return "ok"

    r.owner_handler = handler
    await r.on_message("10", "Membro", False, "Ultron, quem sou eu?", author_id=42)
    text, note = got[0]
    assert text == "Ultron, quem sou eu?"
    assert "Membro" in note and "verificado pelo ID" in note and "Usuario" in note


async def test_service_appends_extra_system(tmp_path):
    from tests.fakes import FakeBrain
    from ultron.chats import ChatStore
    from ultron.confirm import ConfirmBroker
    from ultron.service import Ultron
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    b = FakeBrain()
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": b}, ConfirmBroker())
    c = u.new_chat("claude")
    [e async for e in u.send(c.id, "oi", extra_system="NOTA SECRETA DO SISTEMA")]
    assert "NOTA SECRETA DO SISTEMA" in b.calls[0]["system"] and b.calls[0]["text"] == "oi"


async def test_remote_handle_passes_note_and_dm_note(tmp_path):
    from tests.test_remote import setup
    rc, u, b, sent, _, _ = setup(tmp_path)
    await rc.handle("oi", note="quem fala: Membro")
    assert "quem fala: Membro" in b.calls[0]["system"]
    await rc.on_dm(111, "oi de novo")
    assert "verificado pelo ID" in b.calls[1]["system"]
