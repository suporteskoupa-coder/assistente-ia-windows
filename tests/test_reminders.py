"""Lembretes: armazenamento, ferramentas, disparo, adiar, perdidos e resumo ao abrir."""
import asyncio
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.memory import Conclusion, Vault
from ultron.reminders import ReminderScheduler, ReminderStore, describe_when
from ultron.server import create_app
from ultron.service import Ultron

NOW = datetime(2026, 10, 27, 22, 15)


@pytest.fixture
def store(tmp_path):
    return ReminderStore(tmp_path / "u.db")


# ---------- armazenamento ----------

def test_create_and_list(store):
    r = store.create("treinar", NOW + timedelta(hours=1), now=NOW)
    assert r.status == "pendente" and r.due == "2026-10-27T23:15"
    assert [x.text for x in store.list_pending()] == ["treinar"]


def test_past_rejected(store):
    with pytest.raises(ValueError, match="passou"):
        store.create("x", NOW - timedelta(minutes=1), now=NOW)


def test_bad_repeat_rejected(store):
    with pytest.raises(ValueError):
        store.create("x", NOW + timedelta(hours=1), repeat="mensal", now=NOW)


def test_cancel(store):
    r = store.create("x", NOW + timedelta(hours=1), now=NOW)
    assert store.cancel(r.id) is True
    assert store.list_pending() == [] and store.cancel(999) is False


def test_due_and_fire_once(store):
    r = store.create("pizza", NOW + timedelta(minutes=20), now=NOW)
    later = NOW + timedelta(minutes=21)
    assert [x.id for x in store.due(later)] == [r.id]
    store.mark_fired(r, later)
    assert store.due(later) == [] and store.list_pending() == []


def test_daily_repeat_reschedules_to_future(store):
    r = store.create("remédio", NOW + timedelta(minutes=5), repeat="diario", now=NOW)
    three_days = NOW + timedelta(days=3)
    nxt = store.mark_fired(r, three_days)
    assert nxt.status == "pendente" and nxt.due == "2026-10-30T22:20"


def test_weekly_repeat(store):
    r = store.create("reunião", datetime(2026, 10, 26, 9, 0), repeat="semanal", now=datetime(2026, 10, 26, 8, 0))
    assert store.mark_fired(r, datetime(2026, 10, 26, 9, 0)).due == "2026-11-02T09:00"


def test_snooze(store):
    r = store.create("x", NOW + timedelta(minutes=1), now=NOW)
    store.mark_fired(r, NOW + timedelta(minutes=2))
    s = store.snooze(r.id, 10, NOW + timedelta(minutes=2))
    assert s.status == "pendente" and s.due == "2026-10-27T22:27"


def test_describe_when_in_portuguese():
    assert describe_when(datetime(2026, 10, 28, 18, 0)) == "quarta, 28/10 às 18:00"


# ---------- ferramentas ----------

def registry(tmp_path, store):
    from ultron.tools.registry import build_registry
    cfg = make_cfg(tmp_path)
    return build_registry(cfg, Vault(cfg.vault), lambda t: None, httpx.AsyncClient(), reminders=store, now=lambda: NOW)


async def test_tool_create(tmp_path, store):
    out = await registry(tmp_path, store).call("lembrete_criar", {"texto": "treinar", "quando": "2026-10-28 18:00"})
    assert "quarta, 28/10 às 18:00" in out and "#1" in out
    assert store.list_pending()[0].due == "2026-10-28T18:00"


async def test_tool_create_repeat_and_list_and_cancel(tmp_path, store):
    reg = registry(tmp_path, store)
    await reg.call("lembrete_criar", {"texto": "reunião", "quando": "2026-11-02T09:00", "repetir": "semanal"})
    lst = await reg.call("lembrete_listar", {})
    assert "reunião" in lst and "semanal" in lst
    assert "cancelado" in (await reg.call("lembrete_cancelar", {"id": 1})).lower()
    assert "nenhum" in (await reg.call("lembrete_listar", {})).lower()


@pytest.mark.parametrize("quando", ["amanhã 18h", "2026-10-27 10:00"])
async def test_tool_create_invalid(tmp_path, store, quando):
    out = await registry(tmp_path, store).call("lembrete_criar", {"texto": "x", "quando": quando})
    assert out.startswith("ERRO")


def test_reminder_tools_are_free_and_local(tmp_path, store):
    reg = registry(tmp_path, store)
    for n in ("lembrete_criar", "lembrete_listar", "lembrete_cancelar"):
        assert reg.get(n).confirm is False and reg.get(n).local is True


# ---------- disparo ----------

class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def scheduler(tmp_path, store, clock, notified, events):
    v = Vault(tmp_path / "v")
    v.ensure()
    return ReminderScheduler(store, v, notify=lambda title, text: notified.append((title, text)),
                             publish=events.append, now=clock), v


async def test_tick_fires_notifies_publishes_and_logs(tmp_path, store):
    clock, notified, events = Clock(NOW), [], []
    store.create("tirar a pizza", NOW + timedelta(minutes=20), now=NOW)
    sch, v = scheduler(tmp_path, store, clock, notified, events)
    await sch.tick()
    assert notified == []
    clock.t = NOW + timedelta(minutes=20)
    await sch.tick()
    assert notified == [("Ultron · lembrete", "tirar a pizza")]
    assert events[0]["type"] == "reminder" and events[0]["text"] == "tirar a pizza"
    assert [a["text"] for a in sch.active()] == ["tirar a pizza"]
    assert "lembrete: tirar a pizza" in v.read("Ultron/Diario/2026-10-27.md")
    await sch.tick()
    assert len(notified) == 1  # não dispara duas vezes


async def test_notify_failure_does_not_break(tmp_path, store):
    def boom(title, text):
        raise OSError("sem notificação")
    v = Vault(tmp_path / "v")
    v.ensure()
    events = []
    store.create("x", NOW + timedelta(minutes=1), now=NOW)
    sch = ReminderScheduler(store, v, notify=boom, publish=events.append, now=lambda: NOW + timedelta(minutes=2))
    await sch.tick()
    assert events and events[0]["type"] == "reminder"


async def test_ack_and_snooze(tmp_path, store):
    clock, notified, events = Clock(NOW + timedelta(minutes=2)), [], []
    r = store.create("x", NOW + timedelta(minutes=1), now=NOW)
    sch, _ = scheduler(tmp_path, store, clock, notified, events)
    await sch.tick()
    sch.snooze(r.id, 10)
    assert sch.active() == [] and store.list_pending()[0].due == "2026-10-27T22:27"
    clock.t = NOW + timedelta(minutes=12)
    await sch.tick()
    sch.ack(r.id)
    assert sch.active() == []


async def test_startup_missed_recent_fire_late_old_marked_lost(tmp_path, store):
    store.create("recente", NOW + timedelta(hours=1), now=NOW)
    store.create("antigo", NOW + timedelta(hours=2), now=NOW)
    later = NOW + timedelta(hours=30)
    store._set_due(2, NOW - timedelta(days=1))  # simula um lembrete antigo
    store._set_due(1, later - timedelta(hours=2))
    clock, notified, events = Clock(later), [], []
    sch, _ = scheduler(tmp_path, store, clock, notified, events)
    await sch.startup()
    assert [e["text"] for e in events] == ["recente"] and events[0]["late"] is True
    assert "atrasado" in notified[0][0]
    assert [r.text for r in sch.missed] == ["antigo"]


# ---------- servidor e HUD ----------

def make_app(tmp_path, store, clock):
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    hud = tmp_path / "hud"
    hud.mkdir(exist_ok=True)
    (hud / "index.html").write_text("x")
    broker = ConfirmBroker()
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain()}, broker, now=clock)
    sch = ReminderScheduler(store, v, notify=lambda a, b: None, publish=broker.broadcast, now=clock)
    return TestClient(create_app(u, broker, hud, reminders=sch)), sch, v


async def test_briefing(tmp_path, store):
    clock = Clock(NOW.replace(hour=8))
    store.create("treinar", NOW.replace(hour=18), now=clock.t)
    store.create("amanhã", NOW + timedelta(days=1), now=clock.t)
    c, sch, v = make_app(tmp_path, store, clock)
    v.write("Notas/t.md", "- [ ] a\n- [ ] b\n")
    v.save_conclusions([Conclusion("nova", "média", 1, "2026-10-27", ["#1 x"]),
                        Conclusion("velha", "média", 1, "2026-10-01", ["#1 x"])])
    with c:
        b = c.get("/api/briefing").json()
    assert [r["text"] for r in b["reminders_today"]] == ["treinar"]
    assert b["reminders_today"][0]["when"] == "18:15"
    assert b["pending_count"] == 2
    assert [x["text"] for x in b["new_conclusions"]] == ["nova"]
    assert b["missed"] == []


async def test_reminder_reaches_hud_websocket_and_ack(tmp_path, store):
    clock = Clock(NOW)
    r = store.create("pizza", NOW + timedelta(minutes=1), now=NOW)
    c, sch, _ = make_app(tmp_path, store, clock)
    with c:
        with c.websocket_connect("/ws") as ws:
            clock.t = NOW + timedelta(minutes=2)
            c.portal.call(sch.tick)
            m = ws.receive_json()
            assert m["type"] == "reminder" and m["text"] == "pizza" and m["id"] == r.id
        assert [a["id"] for a in c.get("/api/reminders/active").json()] == [r.id]
        c.post(f"/api/reminders/{r.id}/snooze")
        assert c.get("/api/reminders/active").json() == []
        assert store.list_pending()[0].due == "2026-10-27T22:27"


async def test_prompt_has_current_time(tmp_path, store):
    c, _, _ = make_app(tmp_path, store, Clock(NOW))
    u = c.app.state.ultron
    assert "terça, 27/10/2026 22:15" in u.system_prompt(u.new_chat("claude"))
