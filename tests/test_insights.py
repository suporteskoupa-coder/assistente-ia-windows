"""O Ultron anota sozinho: fatos e pensamentos sobre as pessoas, e conclusões sobre o criador."""
import asyncio
import json
from datetime import datetime

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.events import Event
from ultron.insights import ANALYZE_EVERY, parse_insights
from ultron.memory import Vault
from ultron.people import PeopleStore
from ultron.reminders import ReminderStore
from ultron.server_replies import ServerResponder, StatusStore
from ultron.service import Ultron

NOW = datetime(2026, 10, 28, 20, 0)
REPLY = json.dumps({
    "fatos": [{"texto": "Main de suporte no Deadlock", "confianca": "média"},
              {"texto": "Torce para o Corinthians", "confianca": "baixa"}],
    "esquecer": [],
    "pensamento": "Amigo pergunta pelo Usuario como quem confere se o sol nasceu. Previsível.",
})


def test_parse_insights_tolerates_extra_text():
    out = parse_insights("Claro! Aqui está:\n```json\n" + REPLY + "\n```")
    assert out["fatos"][0]["texto"] == "Main de suporte no Deadlock"
    assert out["pensamento"].startswith("Amigo")
    assert parse_insights("não sei") == {"fatos": [], "esquecer": [], "pensamento": ""}


def test_parse_insights_drops_bad_confidence_and_redacts():
    raw = json.dumps({"fatos": [{"texto": "email contato@exemplo.com", "confianca": "alta"},
                                {"texto": "x", "confianca": "absoluta"}], "pensamento": "ok"})
    out = parse_insights(raw)
    assert out["fatos"] == [{"texto": "email [removido]", "confianca": "alta"}]


def test_person_file_has_readable_name_and_finds_by_id(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    p = PeopleStore(v)
    p.record(111, "Amigo", "oi", "olá", NOW)
    assert (v.root / "Ultron" / "Pessoas" / "Amigo (111).md").exists()
    p.record(111, "Amiguinho", "oi de novo", "olá", NOW)  # apelido novo não cria outro arquivo
    assert len(list((v.root / "Ultron" / "Pessoas").glob("*.md"))) == 1
    assert p.link(111) == "[[Amigo (111)|Amigo]]"


def test_legacy_numeric_file_is_renamed(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    v.write("Ultron/Pessoas/7.md", "# Colega\n\nDiscord ID: 7\nApelidos: Colega\nInterações: 2\n\n## Sobre\nmeu amigo\n\n## Conversas\n")
    p = PeopleStore(v)
    p.record(7, "Colega", "oi", "olá", NOW)
    files = [f.name for f in (v.root / "Ultron" / "Pessoas").glob("*.md")]
    assert files == ["Colega (7).md"] and "meu amigo" in v.read("Ultron/Pessoas/Colega (7).md")


def test_apply_insights_merges_facts_and_thoughts(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    p = PeopleStore(v)
    p.record(1, "Amigo", "oi", "olá", NOW)
    ins = parse_insights(REPLY)
    p.apply_insights(1, ins, NOW)
    p.apply_insights(1, parse_insights(json.dumps({"fatos": [{"texto": "main de suporte no deadlock", "confianca": "alta"}],
                                                    "esquecer": ["Torce para o Corinthians"], "pensamento": "De novo ele."})), NOW)
    text = v.read("Ultron/Pessoas/Amigo (1).md")
    assert "Main de suporte no Deadlock · confiança: alta · visto em 2" in text
    assert "Corinthians" not in text.split("## Pensamentos do Ultron")[0].split("## O que o Ultron sabe")[1]
    assert "Previsível" in text and "De novo ele." in text
    ctx = p.context(1)
    assert "Main de suporte" in ctx and "De novo ele." in ctx


def responder(tmp_path, reply_for_analysis=REPLY):
    cfg = make_cfg(tmp_path, server_enabled=True, server_channels=["10"], owner_name="Usuario",
                   discord_owner_id=42, server_notes="nenhuma", server_per_minute=100)
    v = Vault(cfg.vault)
    v.ensure()
    calls = []

    async def ask(system, text):
        calls.append(system + "\n" + text)
        return reply_for_analysis if "Analise" in system else "resposta"

    r = ServerResponder(cfg, v, ReminderStore(cfg.db_path), StatusStore(cfg.home / "status.json"), ask, now=lambda: NOW)
    return r, calls, v


async def test_server_analyzes_every_n_conversations(tmp_path):
    r, calls, v = responder(tmp_path)
    for i in range(ANALYZE_EVERY):
        await r.on_message("10", "Amigo", False, f"ultron mensagem {i}", author_id=1)
    await r.wait_background()
    analyses = [c for c in calls if "Analise" in c]
    assert len(analyses) == 1
    assert "mensagem 0" in analyses[0] and "mensagem 4" in analyses[0]
    assert "Main de suporte" in v.read("Ultron/Pessoas/Amigo (1).md")
    await r.on_message("10", "Amigo", False, "ultron oi", author_id=1)
    await r.wait_background()
    assert len([c for c in calls if "Analise" in c]) == 1  # só de novo após mais 5


async def test_analysis_failure_does_not_break_replies(tmp_path):
    r, calls, v = responder(tmp_path, reply_for_analysis="lixo")
    for i in range(ANALYZE_EVERY):
        assert await r.on_message("10", "Amigo", False, f"ultron {i}", author_id=1) == "resposta"
    await r.wait_background()


async def test_creator_conclusions_from_chat(tmp_path):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    seen = []

    async def insight_ask(system, text):
        seen.append(system + text)
        return json.dumps({"fatos": [{"texto": "Gosta de jogar à noite", "confianca": "média"}], "pensamento": "Meu criador."})

    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain(script=[Event("text", "ok"), Event("done")])},
               ConfirmBroker(), now=lambda: NOW, insight_ask=insight_ask)
    c = u.new_chat("claude")
    for i in range(ANALYZE_EVERY):
        [e async for e in u.send(c.id, f"hoje joguei até tarde {i}")]
    await u.wait_background()
    assert len(seen) == 1 and "joguei até tarde 4" in seen[0]
    concl = v.conclusions()
    assert concl and concl[0].text == "Gosta de jogar à noite" and concl[0].sources[0].startswith(f"#{c.id}")
