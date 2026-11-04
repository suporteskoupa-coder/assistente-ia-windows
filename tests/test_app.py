import json
import sys

import httpx

from tests.tools.helpers import make_cfg
from ultron.app import build_allowed, ensure_config, write_mcp_config
from ultron.memory import Vault
from ultron.tools.registry import build_registry


def test_ensure_config_copies_example_once(tmp_path):
    p = tmp_path / "Ultron" / "ultron.toml"
    ensure_config(p)
    assert "[apps]" in p.read_text(encoding="utf-8")
    p.write_text("# meu", encoding="utf-8")
    ensure_config(p)
    assert p.read_text(encoding="utf-8") == "# meu"


def test_write_mcp_config(tmp_path):
    out = tmp_path / "mcp.json"
    write_mcp_config(out, tmp_path / "ultron.toml")
    d = json.loads(out.read_text())
    srv = d["mcpServers"]["ultron"]
    assert srv["command"] == sys.executable
    assert srv["args"] == ["-m", "ultron.mcp_server", "--config", str(tmp_path / "ultron.toml")]
    import ultron
    from pathlib import Path
    assert srv["env"]["PYTHONPATH"] == str(Path(ultron.__file__).parent.parent)


def test_build_allowed(tmp_path):
    cfg = make_cfg(tmp_path, claude_allowed_bash=["git status"])
    v = Vault(cfg.vault)
    reg = build_registry(cfg, v, lambda t: None, httpx.AsyncClient())
    allowed = build_allowed(reg, cfg)
    assert "mcp__ultron__abrir_jogo" in allowed
    assert "mcp__ultron__discord_enviar" not in allowed
    assert "mcp__ultron__organizar_pasta" not in allowed
    assert {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "Bash(git status)"} <= set(allowed)
    assert "Bash" not in allowed and "Write" not in allowed


def test_build_wires_reminders(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from ultron.app import build
    cfg_path = tmp_path / "u.toml"
    cfg_path.write_text(f'[paths]\nhome = "{(tmp_path / "home").as_posix()}"\n', encoding="utf-8")
    cfg, app = build(cfg_path, "tk")
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        r = c.get("/api/briefing", headers={"X-Ultron-Token": "tk"})
        assert r.status_code == 200 and "reminders_today" in r.json()


def test_build_wires_insights(tmp_path, monkeypatch):
    from ultron.app import build
    monkeypatch.delenv("ULTRON_DISCORD_TOKEN", raising=False)
    p = tmp_path / "u.toml"
    p.write_text(f'[paths]\nhome = "{(tmp_path / "home").as_posix()}"\n', encoding="utf-8")
    _, app = build(p, "t")
    assert app.state.ultron.insight_ask is not None
