from pathlib import Path

import pytest

from ultron.config import load_config


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "ultron.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_defaults_when_file_minimal(tmp_path, monkeypatch):
    monkeypatch.delenv("ULTRON_DISCORD_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cfg = load_config(write(tmp_path, ""))
    assert cfg.home == tmp_path / "Ultron"
    assert cfg.vault == tmp_path / "Ultron" / "UltronVault"
    assert cfg.db_path == tmp_path / "Ultron" / "ultron.db"
    assert cfg.ollama_url == "http://127.0.0.1:11434"
    assert cfg.ollama_model == "qwen3:8b"
    assert cfg.ollama_ctx == 16384
    assert cfg.claude_bin == "claude"
    assert cfg.core_port == 8765
    assert cfg.hotkey == "ctrl+space"
    assert cfg.steam_root is None
    assert cfg.discord_token is None
    assert cfg.apps == {} and cfg.modes == {} and cfg.discord_channels == {}


def test_modes_and_apps_parsed(tmp_path):
    cfg = load_config(write(tmp_path, '''
[apps]
vscode = "code"
[modes.trabalho]
apps = ["vscode"]
urls = ["https://github.com"]
[discord.channels]
geral = "123"
'''))
    assert cfg.apps == {"vscode": "code"}
    assert cfg.modes["trabalho"].apps == ["vscode"]
    assert cfg.modes["trabalho"].urls == ["https://github.com"]
    assert cfg.discord_channels == {"geral": "123"}


def test_env_overrides_discord_token(tmp_path, monkeypatch):
    monkeypatch.setenv("ULTRON_DISCORD_TOKEN", "env-tok")
    cfg = load_config(write(tmp_path, '[discord]\ntoken = "file-tok"\n'))
    assert cfg.discord_token == "env-tok"


def test_mode_referencing_unknown_app_raises(tmp_path):
    with pytest.raises(ValueError, match="spotify"):
        load_config(write(tmp_path, '[modes.jogo]\napps = ["spotify"]\n'))
