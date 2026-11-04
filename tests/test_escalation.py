"""Escalada: cada amigo vê o Ultron ficar mais vilão conforme conversa com ele."""
from datetime import datetime

import pytest

from tests.tools.helpers import make_cfg
from ultron.escalation import GUARDRAILS, LEVELS, level_for
from ultron.memory import Vault
from ultron.people import PeopleStore
from ultron.reminders import ReminderStore
from ultron.server_replies import ServerResponder, StatusStore

NOW = datetime(2026, 10, 27, 19, 0)


def test_level_grows_with_interactions_and_caps():
    assert level_for(0, step=10) == 0
    assert level_for(9, step=10) == 0
    assert level_for(10, step=10) == 1
    assert level_for(999, step=10) == len(LEVELS) - 1


def test_people_store_counts_and_resets(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    p = PeopleStore(v)
    for i in range(3):
        p.record(1, "Amigo", "oi", "oi", NOW)
    assert p.interactions(1) == 3
    p.reset(1)
    assert p.interactions(1) == 0
    assert "Interações: 0" in v.read("Ultron/Pessoas/Amigo (1).md")


def test_user_edited_interactions_are_respected(tmp_path):
    v = Vault(tmp_path / "v")
    v.ensure()
    p = PeopleStore(v)
    p.record(1, "Amigo", "oi", "oi", NOW)
    v.write("Ultron/Pessoas/Amigo (1).md", v.read("Ultron/Pessoas/Amigo (1).md").replace("Interações: 1", "Interações: 40"))
    p.record(1, "Amigo", "oi", "oi", NOW)
    assert p.interactions(1) == 41


def responder(tmp_path, **kw):
    base = dict(server_enabled=True, server_channels=["10"], owner_name="Usuario", discord_owner_id=42,
                server_notes="nenhuma", server_escalation=True, server_escalation_step=2,
                server_escalation_reset="ultron volta ao normal", server_per_minute=100, server_per_day=1000)
    base.update(kw)
    cfg = make_cfg(tmp_path, **base)
    v = Vault(cfg.vault)
    v.ensure()
    calls = []

    async def ask(system, text):
        calls.append(system)
        return "resposta"

    r = ServerResponder(cfg, v, ReminderStore(cfg.db_path), StatusStore(cfg.home / "status.json"), ask, now=lambda: NOW)
    return r, calls, v


async def test_persona_escalates_per_person(tmp_path):
    r, calls, _ = responder(tmp_path)
    for _ in range(5):
        await r.on_message("10", "Amigo", False, "ultron oi", author_id=1)
    await r.on_message("10", "Visitante", False, "ultron oi", author_id=2)
    assert "nível 0" in calls[0] and "nível 2" in calls[4]
    assert "nível 0" in calls[5]  # cada pessoa tem o próprio nível


async def test_guardrails_always_present_when_escalating(tmp_path):
    r, calls, _ = responder(tmp_path)
    await r.on_message("10", "Amigo", False, "ultron oi", author_id=1)
    assert GUARDRAILS in calls[0]


async def test_reset_phrase_goes_back_to_zero_without_ai(tmp_path):
    r, calls, v = responder(tmp_path)
    for _ in range(6):
        await r.on_message("10", "Amigo", False, "ultron oi", author_id=1)
    n = len(calls)
    out = await r.on_message("10", "Amigo", False, "Ultron, volta ao normal!", author_id=1)
    assert len(calls) == n and "Amigo" in out
    await r.on_message("10", "Amigo", False, "ultron oi", author_id=1)
    assert "nível 0" in calls[-1]


async def test_disabled_has_no_persona(tmp_path):
    r, calls, _ = responder(tmp_path, server_escalation=False)
    await r.on_message("10", "Amigo", False, "ultron oi", author_id=1)
    assert "nível" not in calls[0] and GUARDRAILS not in calls[0]


async def test_creator_never_escalates(tmp_path):
    r, calls, _ = responder(tmp_path)
    got = []

    async def handler(text, note):
        got.append(note)
        return "ok"

    r.owner_handler = handler
    for _ in range(6):
        await r.on_message("10", "Membro", False, "ultron oi", author_id=42)
    assert all("nível" not in n for n in got)


def test_config_escalation(tmp_path):
    from ultron.config import load_config
    p = tmp_path / "u.toml"
    p.write_text("")
    c = load_config(p)
    assert c.server_escalation is False and c.server_escalation_step == 10
    assert c.server_escalation_reset == "ultron volta ao normal"
    p.write_text('[discord.servidor]\nescalada = true\nescalada_passo = 5\nescalada_reset = "ultron chega"\n')
    c = load_config(p)
    assert (c.server_escalation, c.server_escalation_step, c.server_escalation_reset) == (True, 5, "ultron chega")
