"""Configuração do Ultron (arquivo ultron.toml)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Mode:
    apps: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)


@dataclass
class Config:
    vault: Path
    home: Path
    db_path: Path
    apps: dict[str, str]
    modes: dict[str, Mode]
    discord_token: str | None
    discord_channels: dict[str, str]
    steam_root: Path | None
    ollama_url: str
    ollama_model: str
    ollama_ctx: int
    claude_bin: str
    core_port: int
    hotkey: str
    claude_allowed_bash: list[str]
    screen_enabled: bool = True
    ollama_vision_model: str | None = "qwen3-vl:8b"
    remote_enabled: bool = False
    discord_owner_id: int | None = None
    reminders_to_phone: bool = False
    server_enabled: bool = False
    server_wake_word: str = "ultron"
    server_channels: list[str] = field(default_factory=list)
    owner_name: str = ""
    server_notes: str = "publica"  # publica | todas | nenhuma
    server_share_busy: bool = True
    server_per_minute: int = 5
    server_per_day: int = 50
    server_brain: str = "seguir"  # seguir (modo da HUD) | claude | local
    server_escalation: bool = False
    server_escalation_step: int = 10
    server_escalation_reset: str = "ultron volta ao normal"


def user_home() -> Path:
    return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())


def load_config(path: Path) -> Config:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    paths = data.get("paths", {})
    home = Path(paths["home"]).expanduser() if "home" in paths else user_home() / "Ultron"
    vault = Path(paths["vault"]).expanduser() if "vault" in paths else home / "UltronVault"

    apps = {str(k): str(v) for k, v in data.get("apps", {}).items()}
    modes: dict[str, Mode] = {}
    for name, m in data.get("modes", {}).items():
        mode = Mode(apps=list(m.get("apps", [])), urls=list(m.get("urls", [])))
        for app in mode.apps:
            if app not in apps:
                raise ValueError(f"O modo '{name}' usa o app '{app}', que não está em [apps].")
        modes[name] = mode

    discord = data.get("discord", {})
    token = os.environ.get("ULTRON_DISCORD_TOKEN") or discord.get("token") or None
    ollama = data.get("ollama", {})
    claude = data.get("claude", {})
    steam = data.get("steam", {})
    ultron = data.get("ultron", {})
    tela = data.get("tela", {})
    srv = discord.get("servidor", {})
    if srv.get("notas", "publica") not in ("publica", "todas", "nenhuma"):
        raise ValueError("[discord.servidor] notas deve ser publica, todas ou nenhuma.")
    if srv.get("cerebro", "seguir") not in ("seguir", "claude", "local"):
        raise ValueError("[discord.servidor] cerebro deve ser seguir, claude ou local.")

    return Config(
        vault=vault,
        home=home,
        db_path=home / "ultron.db",
        apps=apps,
        modes=modes,
        discord_token=token,
        discord_channels={str(k): str(v) for k, v in discord.get("channels", {}).items()},
        steam_root=Path(steam["root"]) if steam.get("root") else None,
        ollama_url=ollama.get("url", "http://127.0.0.1:11434"),
        ollama_model=ollama.get("model", "qwen3:8b"),
        ollama_ctx=int(ollama.get("ctx", 16384)),
        claude_bin=claude.get("bin", "claude"),
        core_port=int(ultron.get("port", 8765)),
        hotkey=ultron.get("hotkey", "ctrl+space"),
        claude_allowed_bash=list(claude.get("allowed_bash", [])),
        screen_enabled=bool(tela.get("habilitada", True)),
        ollama_vision_model=ollama.get("vision_model", "qwen3-vl:8b") or None,
        remote_enabled=bool(discord.get("controle_remoto", False)),
        discord_owner_id=int(discord["dono_id"]) if str(discord.get("dono_id", "")).strip() else None,
        reminders_to_phone=bool(discord.get("lembretes_no_celular", False)),
        server_enabled=bool(srv.get("ativo", False)),
        server_wake_word=str(srv.get("palavra", "ultron")).strip() or "ultron",
        server_channels=[str(c) for c in srv.get("canais", [])],
        owner_name=str(srv.get("seu_nome", "")).strip(),
        server_notes=srv.get("notas", "publica"),
        server_share_busy=bool(srv.get("mostrar_ocupado", True)),
        server_per_minute=int(srv.get("por_minuto", 5)),
        server_per_day=int(srv.get("por_dia", 50)),
        server_brain=srv.get("cerebro", "seguir"),
        server_escalation=bool(srv.get("escalada", False)),
        server_escalation_step=max(1, int(srv.get("escalada_passo", 10))),
        server_escalation_reset=str(srv.get("escalada_reset", "ultron volta ao normal")).strip() or "ultron volta ao normal",
    )
