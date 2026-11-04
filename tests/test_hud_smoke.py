"""Teste de fumaça da HUD num Chromium de verdade (Playwright)."""
import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

playwright = pytest.importorskip("playwright.sync_api")

from tests.fakes import FakeBrain
from tests.tools.helpers import make_cfg
from ultron.chats import ChatStore
from ultron.confirm import ConfirmBroker
from ultron.memory import Vault
from ultron.server import create_app
from ultron.service import Ultron
from ultron.server_replies import ModeStore
from ultron.system_info import SystemInfo

HUD = Path(__file__).parent.parent / "ultron" / "hud"
TOKEN = "tok-teste"
H = {"X-Ultron-Token": TOKEN}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("hud")
    cfg = make_cfg(tmp)
    v = Vault(cfg.vault)
    v.ensure()
    v.conclude("Joga mais à noite", "média", "2026-10-27")
    broker = ConfirmBroker(timeout=10)
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain("claude"), "ollama": FakeBrain("ollama")}, broker)
    from datetime import datetime, timedelta
    from ultron.reminders import ReminderScheduler, ReminderStore
    rstore = ReminderStore(cfg.db_path)
    now = datetime.now()
    if now.hour < 23:
        rstore.create("treinar", now + timedelta(minutes=30), now=now)
    v.write("Notas/t.md", "- [ ] estudar\n")
    sched = ReminderScheduler(rstore, v, notify=lambda a, b: None, publish=broker.broadcast)
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(create_app(u, broker, HUD, token=TOKEN, reminders=sched, mode=ModeStore(cfg.home / "mode.json"),
                        system=SystemInfo(cfg, cpu=lambda: 33, ram=lambda: 51, smi=lambda: "40, 1000, 8000", processes=lambda: [])), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(5)


@pytest.fixture
def page(server):
    with playwright.sync_playwright() as p:
        exe = "/opt/pw-browsers/chromium"
        b = p.chromium.launch(executable_path=exe if os.path.exists(exe) else None)
        pg = b.new_page(viewport={"width": 1366, "height": 768})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"{server}/?t={TOKEN}")
        pg.wait_for_selector("#core")
        yield pg
        assert errors == []
        b.close()


def test_send_message_shows_reply_and_tool(page):
    page.fill("#input", "abre o cs")
    page.press("#input", "Enter")
    page.wait_for_selector(".msg.assistant:has-text('o CS.')", timeout=5000)
    assert page.locator(".msg.user").last.inner_text() == "abre o cs"
    assert "abrir_jogo" in page.locator(".msg.tool").last.inner_text()
    page.wait_for_selector("#chats .chat:has-text('abre o cs')", timeout=5000)


def test_confirm_card_allows_with_edit(page, server):
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("r", httpx.post(
        f"{server}/api/permission", json={"tool_name": "mcp__ultron__discord_enviar",
                                          "input": {"canal": "geral", "texto": "Entrando no CS"}}, headers=H, timeout=10).json()))
    t.start()
    page.wait_for_selector("#confirm-card:not([hidden])", timeout=5000)
    assert "geral" in page.inner_text("#confirm-card")
    page.fill("#confirm-text", "Entrando no CS em 5 min")
    page.click("#allow")
    t.join(10)
    assert result["r"] == {"allow": True, "input": {"canal": "geral", "texto": "Entrando no CS em 5 min"}}
    page.wait_for_selector("#confirm-card[hidden]", state="attached", timeout=3000)


def test_confirm_card_deny(page, server):
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("r", httpx.post(
        f"{server}/api/permission", json={"tool_name": "Bash", "input": {"command": "dir"}}, headers=H, timeout=10).json()))
    t.start()
    page.wait_for_selector("#confirm-card:not([hidden])", timeout=5000)
    assert "dir" in page.inner_text("#confirm-card")
    page.click("#deny")
    t.join(10)
    assert result["r"]["allow"] is False


def test_compact_mode_hides_sides(page):
    assert page.is_visible("#left")
    page.click("#toggle-compact")
    assert "compact" in page.get_attribute("body", "class")
    assert not page.is_visible("#left") and not page.is_visible("#right")
    assert page.is_visible("#core")


def test_conclusions_and_status_rendered(page):
    page.wait_for_selector("#conclusions :text('Joga mais à noite')", timeout=5000)
    page.wait_for_selector("#stat-notes:not(:empty)", timeout=5000)


def test_brain_selector_switches_new_chat_brain(page):
    page.click("[data-brain='ollama']")
    page.click("#new-chat")
    page.fill("#input", "oi local")
    page.press("#input", "Enter")
    page.wait_for_selector(".msg.assistant", timeout=5000)
    page.wait_for_selector("#chats .chat.on :text('local')", timeout=5000)


def test_markdown_is_rendered_safely(page, server):
    from tests.fakes import FakeBrain  # noqa: F401
    page.evaluate("""() => { const e = document.createElement('div'); e.className='msg assistant'; document.body.appendChild(e);
        setText(e, '**negrito** <img src=x onerror=alert(1)> `cod`'); window.__t = e.innerHTML; }""")
    html = page.evaluate("window.__t")
    assert "<b>negrito</b>" in html and "<code>cod</code>" in html and "<img" not in html



def test_briefing_card_on_open(page):
    page.wait_for_selector("#briefing:not([hidden])", timeout=5000)
    text = page.inner_text("#briefing")
    assert "pendência" in text
    page.click("#briefing-close")
    assert not page.is_visible("#briefing")


def test_reminder_card_ok_and_snooze(page):
    page.evaluate("onEvent({type: 'reminder', id: 1, text: 'tirar a pizza', due: '2026-10-27T22:35', late: false})")
    page.wait_for_selector("#reminder-card:not([hidden])", timeout=3000)
    assert "tirar a pizza" in page.inner_text("#reminder-card")
    assert "remind" in page.get_attribute("body", "class")
    with page.expect_request(lambda r: r.url.endswith("/api/reminders/1/snooze")):
        page.click("#rem-snooze")
    assert not page.is_visible("#reminder-card")
    page.evaluate("onEvent({type: 'reminder', id: 2, text: 'reunião', due: '2026-10-27T22:35', late: true})")
    assert "atrasado" in page.inner_text("#reminder-card").lower()
    with page.expect_request(lambda r: r.url.endswith("/api/reminders/2/ok")):
        page.click("#rem-ok")
    assert not page.is_visible("#reminder-card")



def test_server_reply_shown_in_hud(page):
    page.evaluate("onEvent({type: 'server_reply', author: 'Amigo', question: 'ultron o usuario vai entrar?', reply: 'Pelo status, depois das 21h.'})")
    page.wait_for_selector("#server-log :text('Amigo')", timeout=3000)
    assert "depois das 21h" in page.inner_text("#server-log")



def test_brain_selector_saves_mode(page):
    with page.expect_request(lambda r: r.url.endswith("/api/mode") and r.method == "POST"):
        page.click("[data-brain='ollama']")
    page.click("[data-brain='claude']")


def test_core_is_canvas_driven_by_nucleo(page):
    assert page.evaluate("document.querySelector('#core').tagName") == "CANVAS"
    assert page.evaluate("typeof window.Nucleo") == "object"
    page.wait_for_function("window.Nucleo.state === 'idle'")


def test_system_numbers_from_api(page):
    page.wait_for_function("document.querySelector('#n-cpu').textContent.startsWith('33')", timeout=5000)
    assert page.inner_text("#n-gpu").startswith("40")
    page.wait_for_function("window.Nucleo.load.cpu === 33")


def test_states_reach_nucleo(page, server):
    import threading
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("r", httpx.post(
        f"{server}/api/permission", json={"tool_name": "Bash", "input": {"command": "dir"}}, headers=H, timeout=10).json()))
    t.start()
    page.wait_for_function("window.Nucleo.state === 'confirm'", timeout=5000)
    page.click("#deny")
    t.join(10)
    page.wait_for_function("window.Nucleo.state === 'idle'", timeout=5000)


def test_local_mode_turns_core_into_jarvis(page):
    page.click("[data-brain='ollama']")
    page.wait_for_function("window.Nucleo.local === true")
    page.click("[data-brain='claude']")
    page.wait_for_function("window.Nucleo.local === false")


def test_jarvis_mesh_has_no_center_spokes():
    import re
    src = (HUD / "nucleo.js").read_text(encoding="utf-8")
    assert "if (PTS[i].inner) continue" in src and "!PTS[j].inner" in src
