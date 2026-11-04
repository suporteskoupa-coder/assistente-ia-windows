"""Cofre conectado: notas com [[links]] para o grafo do Obsidian virar um cérebro."""
import re
from datetime import datetime

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.memory import HUB, Conclusion, Vault, chat_link
from ultron.people import PeopleStore
from ultron.service import Ultron

NOW = datetime(2026, 10, 27, 18, 43)
LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def links(text):
    return set(LINK.findall(text))


def setup(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain()}, ConfirmBroker(), now=lambda: NOW)
    return u, v


def test_hub_links_memory_and_personality(tmp_path):
    _, v = setup(tmp_path)
    hub = v.read(HUB)
    assert {"Personalidade", "perfil", "preferencias", "conclusoes"} <= links(hub)
    for rel in ("Ultron/Memoria/perfil.md", "Ultron/Memoria/conclusoes.md", "Ultron/Personalidade.md"):
        assert "Ultron" in links(v.read(rel))


def test_chat_link_format():
    assert chat_link(12, "Noite de jogo") == "[[Chat 12|Noite de jogo]]"
    assert chat_link(3, "a | b ] c") == "[[Chat 3|a b c]]"


def test_conclusion_sources_are_links_and_parse_back(tmp_path):
    _, v = setup(tmp_path)
    c = Conclusion("Joga à noite", "média", 2, "2026-10-27", ["#12 Noite de jogo", "#15 Abre o CS"])
    v.save_conclusions([c])
    text = v.read("Ultron/Memoria/conclusoes.md")
    assert "fontes: [[Chat 12|Noite de jogo]]; [[Chat 15|Abre o CS]]" in text
    assert v.conclusions() == [c]


def test_legacy_hash_sources_still_parse(tmp_path):
    _, v = setup(tmp_path)
    v.write("Ultron/Memoria/conclusoes.md", "# C\n\n- X · confiança: alta · visto em 2 chats · 2026-10-01 · fontes: #1 a; #2 b\n")
    assert v.conclusions()[0].sources == ["#1 a", "#2 b"]


async def test_chat_note_created_with_day_and_hub_links(tmp_path):
    u, v = setup(tmp_path)
    c = u.new_chat("claude")
    [e async for e in u.send(c.id, "abre o cs agora")]
    note = v.read(f"Ultron/Chats/Chat {c.id}.md")
    assert {"2026-10-27", "Ultron"} <= links(note)
    diary = v.read("Ultron/Diario/2026-10-27.md")
    assert f"Chat {c.id}" in links(diary) and "Ultron" in links(diary)


async def test_close_chat_writes_summary_into_chat_note(tmp_path):
    u, v = setup(tmp_path)
    c = u.new_chat("claude")
    [e async for e in u.send(c.id, "fala de jogos")]
    await u.close_chat(c.id)
    files = list((v.root / "Ultron" / "Chats").glob("*.md"))
    assert len(files) == 1 and "resumo do chat" in files[0].read_text(encoding="utf-8")


def test_people_notes_link_hub_and_days(tmp_path):
    _, v = setup(tmp_path)
    p = PeopleStore(v)
    p.record(111, "Amigo", "oi", "olá", NOW)
    note = v.read("Ultron/Pessoas/Amigo (111).md")
    assert {"Ultron", "2026-10-27"} <= links(note)
    assert p.interactions(111) == 1 and "oi" in p.context(111)


def test_server_diary_links_person(tmp_path):
    import asyncio
    from ultron.reminders import ReminderStore
    from ultron.server_replies import ServerResponder, StatusStore
    cfg = make_cfg(tmp_path, server_enabled=True, server_channels=["10"], owner_name="Usuario", server_notes="nenhuma")
    v = Vault(cfg.vault)
    v.ensure()

    async def ask(s, t):
        return "resposta"

    r = ServerResponder(cfg, v, ReminderStore(cfg.db_path), StatusStore(cfg.home / "status.json"), ask, now=lambda: NOW)
    asyncio.run(r.on_message("10", "Amigo", False, "ultron oi", author_id=111))
    assert "Amigo (111)" in links(v.read("Ultron/Diario/2026-10-27.md"))


def test_link_existing_vault_migration(tmp_path):
    from ultron.link_vault import link_vault
    v = Vault(tmp_path / "v")
    (v.root / "Ultron" / "Diario").mkdir(parents=True)
    (v.root / "Ultron" / "Pessoas").mkdir(parents=True)
    (v.root / "Ultron" / "Memoria").mkdir(parents=True)
    v.write("Ultron/Diario/2026-10-20.md", "# Diário 2026-10-20\n\n- 10:00 algo\n")
    v.write("Ultron/Pessoas/7.md", "# Colega\n\nDiscord ID: 7\nApelidos: Colega\nInterações: 3\n\n## Sobre\nmelhor amigo\n\n## Conversas\n- 2026-10-20 10:00 · oi → olá\n")
    v.write("Ultron/Memoria/conclusoes.md", "# C\n\n- X · confiança: alta · visto em 2 chats · 2026-10-01 · fontes: #1 a; #2 b\n")
    n = link_vault(v)
    assert n >= 3
    assert "Ultron" in links(v.read("Ultron/Diario/2026-10-20.md"))
    colega = v.read("Ultron/Pessoas/Colega (7).md")
    assert "melhor amigo" in colega and "2026-10-20" in links(colega) and "Interações: 3" in colega
    assert "[[Chat 1|a]]" in v.read("Ultron/Memoria/conclusoes.md")
    assert link_vault(v) == 0  # rodar de novo não muda nada
