"""Abrir apps e ativar modos (conjuntos de apps e sites)."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from typing import Callable

from ultron.config import Config
from ultron.winproc import no_window_kwargs

Launcher = Callable[[str], None]


def default_launcher(target: str) -> None:
    """Abre um app, arquivo, URL ou URI (steam://, spotify:)."""
    if sys.platform == "win32":
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return
        except OSError:
            subprocess.Popen(target, shell=True, **no_window_kwargs())
            return
    if "://" in target or target.endswith(":"):
        webbrowser.open(target)
    else:
        subprocess.Popen([target])


def _find(options: dict, name: str):
    key = name.strip().lower()
    for k, v in options.items():
        if k.lower() == key:
            return k, v
    return None, None


def open_app(cfg: Config, name: str, launch: Launcher) -> str:
    key, target = _find(cfg.apps, name)
    if key is None:
        known = ", ".join(sorted(cfg.apps)) or "nenhum"
        return f"ERRO: não conheço o app '{name}'. Apps configurados: {known}."
    launch(target)
    return f"Abrindo {key}."


def activate_mode(cfg: Config, name: str, launch: Launcher) -> str:
    key, mode = _find(cfg.modes, name)
    if key is None:
        known = ", ".join(sorted(cfg.modes)) or "nenhum"
        return f"ERRO: não conheço o modo '{name}'. Modos configurados: {known}."
    for app in mode.apps:
        launch(cfg.apps[app])
    for url in mode.urls:
        launch(url)
    return f"Modo {key} ativado: {len(mode.apps)} apps e {len(mode.urls)} sites."
