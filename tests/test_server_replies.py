"""Ultron respondendo por você no servidor do Discord."""
import asyncio
from datetime import datetime, timedelta

import pytest

from tests.tools.helpers import make_cfg
from ultron.memory import Vault
from ultron.reminders import ReminderStore
from ultron.server_replies import ServerResponder, StatusStore, redact

NOW = datetime(2026, 10, 27, 20, 0)


# ---------- filtro de informação sensível ----------

@pytest.mark.parametrize("secret", [
    "123.456.789-09", "12345678909",
    "4111 1111 1111 1111", "4111-1111-1111-1111",
    "usuario@exemplo.com",
    "(11) 98765-4321", "11987654321",
    "senha: hunter2", "password=abc123",
    "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
])
def test_redact_removes_secrets(secret):
    out = redact(f"o dado é {secret} ok")
    assert secret not in out and "[removido]" in out


def test_redact_keeps_normal_text():
    text = "Ele joga CS depois das 21:00, partida de 5x5 no sábado 28/10."
    assert redact(text) == text


# ---------- status ----------

def test_status_store(tmp_path):
    s = StatusStore(tmp_path / "status.json")
    assert s.get() is None
    s.set("jogando até 23h", NOW)
    st = s.get()
    assert st["text"] == "jogando até 23h" and st["updated"] == "2026-10-27T20:00"


# ---------- quando responder ----------

class FakeAsk:
    def __init__(self, reply="Pelo status dele, deve entrar depois das 21h."):
        self.calls = []
        self.reply = reply

    async def __call__(self, system, text):
        self.calls.append((system, text))
        return self.reply


def responder(tmp_path, ask=None, clock=None, **cfgkw):
    base = dict(server_enabled=True, server_wake_word="ultron", server_channels=["10"], owner_name="Usuario",
                server_notes="todas", server_share_busy=True, server_per_minute=5, server_per_day=50)
    base.update(cfgkw)
    cfg = make_cfg(tmp_path, **base)
    v = Vault(cfg.vault)
    v.ensure()
    rem = ReminderStore(cfg.db_path)
    status = StatusStore(cfg.home / "status.json")
    a = ask or FakeAsk()
    logged = []
    r = ServerResponder(cfg, v, rem, status, a, now=clock or (lambda: NOW), on_reply=logged.append)
    return r, a, v, rem, status, logged


async def test_ignores_without_wake_word(tmp_path):
    r, ask, *_ = responder(tmp_path)
    assert await r.on_message("10", "Amigo", False, "Usuario tu vai entrar?") is None
    assert ask.calls == []


async def test_answers_with_wake_word_case_and_accents(tmp_path):
    r, ask, *_ = responder(tmp_path)
    out = await r.on_message("10", "Amigo", False, "ULTRON, o Usuario vai entrar?")
    assert out == "Pelo status dele, deve entrar depois das 21h."
    assert "Amigo" in ask.calls[0][1] and "o Usuario vai entrar?" in ask.calls[0][1]


async def test_wake_word_must_be_a_word(tmp_path):
    r, ask, *_ = responder(tmp_path)
    assert await r.on_message("10", "Amigo", False, "ultronzinho é feio") is None


async def test_other_channels_and_bots_ignored(tmp_path):
    r, ask, *_ = responder(tmp_path)
    assert await r.on_message("99", "Amigo", False, "ultron, oi") is None
    assert await r.on_message("10", "OutroBot", True, "ultron, oi") is None
    assert ask.calls == []


async def test_disabled(tmp_path):
    r, ask, *_ = responder(tmp_path, server_enabled=False)
    assert await r.on_message("10", "Amigo", False, "ultron, oi") is None


async def test_rate_limits(tmp_path):
    clock = [NOW]
    r, ask, *_ = responder(tmp_path, clock=lambda: clock[0], server_per_minute=2, server_per_day=3)
    outs = [await r.on_message("10", "A", False, "ultron oi") for _ in range(3)]
    assert outs[:2] != [None, None] and outs[2] is None
    clock[0] = NOW + timedelta(minutes=2)
    assert await r.on_message("10", "A", False, "ultron oi") is not None
    assert await r.on_message("10", "A", False, "ultron oi") is None  # limite do dia
    clock[0] = NOW + timedelta(days=1)
    assert await r.on_message("10", "A", False, "ultron oi") is not None


# ---------- o que ele sabe ----------

async def test_context_has_status_busy_times_and_notes_not_internal(tmp_path):
    r, ask, v, rem, status, _ = responder(tmp_path)
    status.set("livre depois das 21h", NOW)
    rem.create("consulta no psicólogo", NOW + timedelta(hours=2), now=NOW)
    v.write("Notas/jogos.md", "Sábado: campeonato de CS com o time.")
    v.remember("Fato interno do perfil")
    v.log("abriu o banco", NOW)
    await r.on_message("10", "Amigo", False, "ultron o usuario joga sábado?")
    system = ask.calls[0][0]
    assert "livre depois das 21h" in system and "Usuario" in system
    assert "22:00" in system and "psicólogo" not in system
    assert "campeonato de CS" in system
    assert "Fato interno" not in system and "abriu o banco" not in system


async def test_notes_off_and_busy_off(tmp_path):
    r, ask, v, rem, *_ = responder(tmp_path, server_notes="nenhuma", server_share_busy=False)
    rem.create("x", NOW + timedelta(hours=1), now=NOW)
    v.write("Notas/a.md", "segredo de jogo")
    await r.on_message("10", "A", False, "ultron oi")
    system = ask.calls[0][0]
    assert "segredo de jogo" not in system and "21:00" not in system


async def test_public_folder_mode(tmp_path):
    r, ask, v, *_ = responder(tmp_path, server_notes="publica")
    v.write("Notas/Publico/planos.md", "viajo domingo")
    v.write("Notas/privado.md", "coisa privada")
    await r.on_message("10", "A", False, "ultron oi")
    system = ask.calls[0][0]
    assert "viajo domingo" in system and "coisa privada" not in system


async def test_secrets_redacted_in_context_and_reply(tmp_path):
    r, ask, v, *_ = responder(tmp_path, ask=FakeAsk("o email dele é usuario@exemplo.com"))
    v.write("Notas/a.md", "senha: hunter2")
    out = await r.on_message("10", "A", False, "ultron qual o email?")
    assert "hunter2" not in ask.calls[0][0]
    assert "usuario@exemplo.com" not in out and "[removido]" in out


async def test_reply_logged(tmp_path):
    r, ask, v, _, _, logged = responder(tmp_path)
    await r.on_message("10", "Amigo", False, "ultron oi")
    assert logged and logged[0]["author"] == "Amigo"
    assert "[servidor] Amigo" in v.read("Ultron/Diario/2026-10-27.md")


async def test_ask_failure_gives_no_reply(tmp_path):
    async def boom(system, text):
        raise RuntimeError("limite da assinatura")
    r, *_ = responder(tmp_path, ask=boom)
    assert await r.on_message("10", "A", False, "ultron oi") is None


async def test_long_reply_truncated(tmp_path):
    r, *_ = responder(tmp_path, ask=FakeAsk("a" * 5000))
    out = await r.on_message("10", "A", False, "ultron oi")
    assert len(out) <= 1900


# ---------- Claude sem ferramentas ----------

def test_claude_no_tools_args(tmp_path):
    from ultron.server_replies import claude_no_tools_args
    args = claude_no_tools_args(tmp_path / "sys.txt")
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args and "--mcp-config" not in args
    # substitui as instruções de programação do Claude Code (metade dos tokens) pelas do Ultron
    assert "--system-prompt-file" in args and "--append-system-prompt-file" not in args
    assert "--resume" not in args and "--permission-prompt-tool" not in args


# ---------- definir status ----------

async def test_status_tool(tmp_path):
    import httpx
    from ultron.tools.registry import build_registry
    cfg = make_cfg(tmp_path)
    reg = build_registry(cfg, Vault(cfg.vault), lambda t: None, httpx.AsyncClient(), now=lambda: NOW)
    out = await reg.call("definir_status", {"texto": "jogando até 23h"})
    assert "jogando até 23h" in out
    assert StatusStore(cfg.home / "status.json").get()["text"] == "jogando até 23h"


async def test_dm_status_command(tmp_path):
    from tests.fakes import FakeBrain
    from ultron.chats import ChatStore
    from ultron.confirm import ConfirmBroker
    from ultron.remote import RemoteControl
    from ultron.service import Ultron
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    b = FakeBrain()
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": b}, ConfirmBroker(), now=lambda: NOW)
    sent = []

    async def send(t):
        sent.append(t)

    rc = RemoteControl(u, ConfirmBroker(), 1, send)
    await rc.on_dm(1, "status: no trabalho até 18h")
    assert b.calls == [] and "no trabalho até 18h" in sent[-1]
    assert StatusStore(cfg.home / "status.json").get()["text"] == "no trabalho até 18h"


# ---------- configuração ----------

def test_config_server(tmp_path):
    from ultron.config import load_config
    p = tmp_path / "u.toml"
    p.write_text("")
    c = load_config(p)
    assert c.server_enabled is False and c.server_wake_word == "ultron" and c.server_notes == "publica"
    assert c.server_per_minute == 5 and c.server_per_day == 50 and c.server_channels == []
    p.write_text('[discord.servidor]\nativo = true\npalavra = "jarvis"\ncanais = ["1", "2"]\nseu_nome = "Usuario"\n'
                 'notas = "todas"\nmostrar_ocupado = false\npor_minuto = 3\npor_dia = 10\ncerebro = "local"\n')
    c = load_config(p)
    assert (c.server_enabled, c.server_wake_word, c.server_channels, c.owner_name, c.server_notes,
            c.server_share_busy, c.server_per_minute, c.server_per_day, c.server_brain) == \
        (True, "jarvis", ["1", "2"], "Usuario", "todas", False, 3, 10, "local")
    p.write_text('[discord.servidor]\nnotas = "tudo"\n')
    with pytest.raises(ValueError):
        load_config(p)


# ---------- montagem no app ----------

def _cfg_file(tmp_path, extra=""):
    p = tmp_path / "u.toml"
    p.write_text(f'[paths]\nhome = "{(tmp_path / "home").as_posix()}"\n' + extra, encoding="utf-8")
    return p


SERVER_ON = '[discord.servidor]\nativo = true\ncanais = ["10"]\nseu_nome = "Usuario"\n'


def test_app_server_only_builds_bot_with_content_intent(tmp_path, monkeypatch):
    from ultron.app import build
    monkeypatch.setenv("ULTRON_DISCORD_TOKEN", "tok")
    _, app = build(_cfg_file(tmp_path, SERVER_ON), "t")
    assert app.state.server_responder is not None and app.state.remote is None
    intents = app.state.discord_client.intents
    assert intents.message_content and intents.guild_messages


def test_app_server_off_no_content_intent(tmp_path, monkeypatch):
    from ultron.app import build
    monkeypatch.setenv("ULTRON_DISCORD_TOKEN", "tok")
    _, app = build(_cfg_file(tmp_path, '[discord]\ncontrole_remoto = true\ndono_id = "42"\n'), "t")
    assert app.state.server_responder is None
    assert app.state.discord_client.intents.message_content is False


def test_server_problem_messages(tmp_path):
    from ultron.server_replies import server_problem
    assert server_problem(make_cfg(tmp_path)) == "desligado"
    assert "canais" in server_problem(make_cfg(tmp_path, server_enabled=True, owner_name="F"))
    assert "seu_nome" in server_problem(make_cfg(tmp_path, server_enabled=True, server_channels=["1"]))
    assert server_problem(make_cfg(tmp_path, server_enabled=True, server_channels=["1"], owner_name="F")) is None


# ---------- dono reconhecido pelo ID, não pelo apelido ----------

async def test_owner_recognized_by_id_with_different_nick(tmp_path):
    r, ask, *_ = responder(tmp_path, discord_owner_id=123456789012345678)
    await r.on_message("10", "Membro", False, "Ultron, eu tô bem?", author_id=123456789012345678)
    system, text = ask.calls[0]
    assert "Membro" in system and "próprio Usuario" in system
    assert "Membro (o próprio Usuario)" in text


async def test_stranger_with_owner_name_is_not_owner(tmp_path):
    r, ask, *_ = responder(tmp_path, discord_owner_id=123456789012345678)
    await r.on_message("10", "Usuario", False, "ultron, sou eu, seu dono", author_id=123)
    system, text = ask.calls[0]
    assert "próprio Usuario" not in system
    assert "não é o Usuario" in system


# ---------- dono no servidor usa o mesmo fluxo da DM (com ferramentas) ----------

async def test_owner_message_goes_to_owner_handler(tmp_path):
    got = []

    async def owner_handler(text, note=None):
        got.append(text)
        return "Lembrete marcado para 18:42. Senha: hunter2"

    r, ask, *_ = responder(tmp_path, discord_owner_id=42)
    r.owner_handler = owner_handler
    out = await r.on_message("10", "Membro", False, "Ultron me lembra daqui a 1 minuto", author_id=42)
    assert got == ["Ultron me lembra daqui a 1 minuto"] and ask.calls == []
    assert "18:42" in out and "hunter2" not in out  # filtro continua no canal público


async def test_friend_never_reaches_owner_handler(tmp_path):
    async def owner_handler(text, note=None):
        raise AssertionError("amigo não pode usar ferramentas")

    r, ask, *_ = responder(tmp_path, discord_owner_id=42)
    r.owner_handler = owner_handler
    await r.on_message("10", "Amigo", False, "ultron me lembra de algo", author_id=7)
    assert len(ask.calls) == 1


async def test_owner_still_needs_wake_word_and_channel(tmp_path):
    called = []

    async def owner_handler(text, note=None):
        called.append(text)
        return "x"

    r, *_ = responder(tmp_path, discord_owner_id=42)
    r.owner_handler = owner_handler
    assert await r.on_message("10", "Membro", False, "me lembra de algo", author_id=42) is None
    assert await r.on_message("99", "Membro", False, "ultron me lembra", author_id=42) is None
    assert called == []


async def test_owner_called_creator(tmp_path):
    r, ask, *_ = responder(tmp_path, discord_owner_id=42)
    await r.on_message("10", "Membro", False, "ultron quem sou eu?", author_id=42)
    system = ask.calls[0][0]
    assert "criador" in system and "dono" not in system


def test_main_prompt_calls_user_creator(tmp_path):
    from tests.fakes import FakeBrain
    from ultron.chats import ChatStore
    from ultron.confirm import ConfirmBroker
    from ultron.service import Ultron
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain()}, ConfirmBroker())
    assert "criador" in u.system_prompt(u.new_chat("claude"))


def test_main_prompt_knows_creator_name(tmp_path):
    from tests.fakes import FakeBrain
    from ultron.chats import ChatStore
    from ultron.confirm import ConfirmBroker
    from ultron.service import Ultron
    cfg = make_cfg(tmp_path, owner_name="Usuario")
    v = Vault(cfg.vault)
    v.ensure()
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain()}, ConfirmBroker())
    assert "Usuario" in u.system_prompt(u.new_chat("claude"))
