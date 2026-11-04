"""Ponto de entrada: `python -m ultron`. Sobe o núcleo, abre a janela da HUD e registra o atalho."""
from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx
import uvicorn

from ultron.brains.claude_code import MCP_PREFIX, ClaudeCodeBrain
from ultron.brains.ollama import OllamaBrain
from ultron.chats import ChatStore
from ultron.config import Config, load_config, user_home
from ultron.confirm import ConfirmBroker
from ultron.memory import Vault
from ultron.reflect import scheduler
from ultron.reminders import ReminderScheduler, ReminderStore, windows_notify
from ultron.remote import RemoteControl, remote_problem
from ultron.screen import ScreenCapturer
from ultron.system_info import SystemInfo
from ultron.server import create_app
from ultron.service import Ultron
from ultron.tools.apps import default_launcher
from ultron.tools.registry import Registry, build_registry

PKG = Path(__file__).parent
CLAUDE_FREE_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]


def ensure_config(path: Path) -> Path:
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(PKG / "ultron.example.toml", path)
    return path


def write_mcp_config(out: Path, config_path: Path, token: str = "") -> Path:
    data = {"mcpServers": {"ultron": {
        "command": sys.executable,
        "args": ["-m", "ultron.mcp_server", "--config", str(config_path)],
        # PYTHONPATH: acha o pacote do Ultron de qualquer pasta. ULTRON_TOKEN: autoriza pedir confirmações.
        "env": {"PYTHONPATH": str(PKG.parent), "ULTRON_TOKEN": token},
    }}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out


def build_allowed(reg: Registry, cfg: Config) -> list[str]:
    tools = [MCP_PREFIX + t.name for t in reg.all() if not t.confirm] + [MCP_PREFIX + "ver_tela"]
    return tools + CLAUDE_FREE_TOOLS + [f"Bash({c})" for c in cfg.claude_allowed_bash]


def fix_stdio(home: Path) -> Path:
    """Sem console (pythonw.exe), stdout/stderr são None e o uvicorn quebra. Manda tudo para um log."""
    log = Path(home) / "ultron.log"
    if sys.stdout is None or sys.stderr is None:
        log.parent.mkdir(parents=True, exist_ok=True)
        f = open(log, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = f
        if sys.stderr is None:
            sys.stderr = f
    return log


def server_config(app, port: int) -> uvicorn.Config:
    return uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", use_colors=False)


def show_fatal(message: str) -> None:
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Ultron", 0x10)


def phone_notifier(send_to_phone, notify_windows=windows_notify):
    """Lembrete vai para o celular (DM) e para a notificação do Windows."""
    def notify(title: str, text: str) -> None:
        asyncio.get_running_loop().create_task(send_to_phone(f"⏰ {text}"))
        notify_windows(title, text)
    return notify


def build(config_path: Path, token: str = ""):
    cfg = load_config(config_path)
    vault = Vault(cfg.vault)
    vault.ensure()
    http = httpx.AsyncClient()
    reminders = ReminderStore(cfg.db_path)
    reg = build_registry(cfg, vault, default_launcher, http, reminders=reminders)
    broker = ConfirmBroker()
    capturer = ScreenCapturer()
    mcp = write_mcp_config(cfg.home / "mcp.json", config_path, token)
    brains = {
        "claude": ClaudeCodeBrain(cfg, mcp, build_allowed(reg, cfg), cfg.home),
        "ollama": OllamaBrain(cfg, reg, broker, http, capturer=capturer),
    }
    from ultron.server_replies import (ModeStore, ServerResponder, StatusStore, make_claude_ask, make_mode_ask,
                                       make_ollama_ask, server_problem)

    mode = ModeStore(cfg.home / "mode.json")
    # chamadas sem ferramentas para anotar fatos e pensamentos (seguem o modo CLAUDE/LOCAL da HUD)
    quiet_ask = make_mode_ask("seguir", mode, make_claude_ask(cfg, cfg.home / "servidor"), make_ollama_ask(cfg, http))
    ultron = Ultron(cfg, ChatStore(cfg.db_path), vault, brains, broker, insight_ask=quiet_ask)

    remote, client, responder = None, None, None
    holder = {}

    async def send(text: str) -> None:
        await holder["send"](text)

    problem = remote_problem(cfg)
    if problem is None:
        remote = RemoteControl(ultron, broker, cfg.discord_owner_id, send, mode=mode)
    elif problem != "desligado":
        print(f"Controle pelo celular desligado: {problem}", file=sys.stderr)
    sproblem = server_problem(cfg)
    if sproblem is None:
        ask = make_mode_ask(cfg.server_brain, mode, make_claude_ask(cfg, cfg.home / "servidor"),
                            make_ollama_ask(cfg, http))
        responder = ServerResponder(cfg, vault, reminders, StatusStore(cfg.home / "status.json"), ask,
                                    on_reply=broker.broadcast)
    elif sproblem != "desligado":
        print(f"Respostas no servidor desligadas: {sproblem}", file=sys.stderr)
    if responder and remote:
        responder.owner_handler = remote.handle  # você no servidor = mesmo poder da DM
    if remote or responder:
        try:
            from ultron.discord_bot import make_client

            client, holder["send"] = make_client(cfg.discord_owner_id, remote.on_dm if remote else None,
                                                 responder.on_message if responder else None)
        except ImportError:
            print("Discord: instale o discord.py (rode o instalador de novo).", file=sys.stderr)
            remote = responder = None

    notify = phone_notifier(remote.send) if (remote and cfg.reminders_to_phone) else windows_notify
    reminder_scheduler = ReminderScheduler(reminders, vault, notify=notify, publish=broker.broadcast)
    app = create_app(ultron, broker, PKG / "hud", token=token or None, capturer=capturer,
                     reminders=reminder_scheduler, remote=remote, mode=mode, system=SystemInfo(cfg))
    app.state.remote = remote
    app.state.discord_client = client
    app.state.server_responder = responder
    app.state.capturer = capturer

    @app.on_event("startup")
    async def _start_background():
        asyncio.create_task(reminder_scheduler.run())
        if remote is not None:
            remote.start()
        if client is not None:
            async def run_bot():
                try:
                    await client.start(cfg.discord_token)
                except Exception as e:  # token errado, sem internet etc.
                    vault.log(f"[celular] bot do Discord não conectou: {e}", ultron.now())
                    print(f"Bot do Discord não conectou: {e}", file=sys.stderr)

            asyncio.create_task(run_bot())
        if shutil.which(cfg.claude_bin):
            asyncio.create_task(scheduler(vault, brains["claude"]))

    return cfg, app


def start_server(cfg: Config, app) -> uvicorn.Server:
    server = uvicorn.Server(server_config(app, cfg.core_port))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError(f"O núcleo não subiu na porta {cfg.core_port}. Outra instância do Ultron já está aberta?")


class WindowApi:
    """Funções que a HUD chama pela ponte do pywebview."""

    # Atributos com "_": o pywebview não varre nem expõe ao JavaScript.
    def __init__(self):
        self._window = None
        self._compact = False

    def window_set(self, window) -> None:
        self._window = window

    def set_compact(self, on: bool) -> None:
        import webview

        self._compact = bool(on)
        w = self._window
        if self._compact:
            screen = webview.screens[0]
            w.restore()
            w.resize(360, 440)
            w.move(screen.width - 380, screen.height - 500)
            w.on_top = True
        else:
            w.on_top = False
            w.maximize()

    def toggle(self) -> None:
        self.set_compact(not self._compact)
        self._window.evaluate_js(f"window.ultron.setCompact({'true' if self._compact else 'false'})")

    def attention(self) -> None:
        if self._compact:
            return
        self._window.show()

    def quit(self) -> None:
        self._window.destroy()


def main() -> None:
    fix_stdio(user_home() / "Ultron")
    try:
        config_path = ensure_config(user_home() / "Ultron" / "ultron.toml")
        token = secrets.token_urlsafe(24)
        cfg, app = build(config_path, token)
        start_server(cfg, app)
    except Exception as e:
        show_fatal(f"O Ultron não conseguiu iniciar:\n\n{e}\n\nDetalhes em %USERPROFILE%\\Ultron\\ultron.log")
        raise
    url = f"http://127.0.0.1:{cfg.core_port}/?t={token}"
    try:
        import webview
    except ImportError:
        print(f"pywebview não instalado: abrindo a HUD no navegador em {url}")
        webbrowser.open(url)
        while True:
            time.sleep(3600)

    api = WindowApi()
    window = webview.create_window("Ultron", url, js_api=api, frameless=True, easy_drag=False,
                                       maximized=True, background_color="#08090b")
    api.window_set(window)
    # esconde a HUD durante o print para ela não aparecer na imagem
    app.state.capturer.set_window_hooks(window.hide, window.show)
    try:
        import keyboard

        keyboard.add_hotkey(cfg.hotkey, api.toggle)
    except Exception as e:  # sem atalho, a HUD continua funcionando pelo botão
        print(f"Atalho {cfg.hotkey} indisponível: {e}")
    webview.start()


if __name__ == "__main__":
    main()
