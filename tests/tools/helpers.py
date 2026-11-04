from pathlib import Path

from ultron.config import Config, Mode


def make_cfg(tmp_path: Path, **kw) -> Config:
    base = dict(
        vault=tmp_path / "vault", home=tmp_path / "home", db_path=tmp_path / "home" / "u.db",
        apps={"vscode": "code", "spotify": "spotify:"},
        modes={"trabalho": Mode(apps=["vscode", "spotify"], urls=["https://github.com"])},
        discord_token="tok", discord_channels={"geral": "111"},
        steam_root=None, ollama_url="http://ollama", ollama_model="m", ollama_ctx=100,
        claude_bin="claude", core_port=8765, hotkey="ctrl+space", claude_allowed_bash=[],
        screen_enabled=True, ollama_vision_model=None,
        remote_enabled=False, discord_owner_id=None, reminders_to_phone=False,
        server_enabled=False, server_wake_word="ultron", server_channels=[], owner_name="",
        server_notes="publica", server_share_busy=True, server_per_minute=5, server_per_day=50, server_brain="seguir",
        server_escalation=False, server_escalation_step=10, server_escalation_reset="ultron volta ao normal",
    )
    base.update(kw)
    return Config(**base)


def make_steam(root: Path, libs: dict[str, list[tuple[str, str]]]) -> Path:
    """libs: caminho da biblioteca -> [(appid, nome)]. A primeira é a raiz."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "steamapps").mkdir(exist_ok=True)
    entries = []
    for i, (lib, games) in enumerate(libs.items()):
        lib_path = Path(lib)
        (lib_path / "steamapps").mkdir(parents=True, exist_ok=True)
        escaped = str(lib_path).replace("\\", "\\\\")
        entries.append(f'\t"{i}"\n\t{{\n\t\t"path"\t\t"{escaped}"\n\t\t"apps"\n\t\t{{\n\t\t}}\n\t}}')
        for appid, name in games:
            (lib_path / "steamapps" / f"appmanifest_{appid}.acf").write_text(
                f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"{name}"\n}}\n',
                encoding="utf-8",
            )
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n' + "\n".join(entries) + "\n}\n", encoding="utf-8"
    )
    return root
