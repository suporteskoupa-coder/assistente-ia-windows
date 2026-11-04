"""Ajustes para processos no Windows."""
from __future__ import annotations

import sys

CREATE_NO_WINDOW = 0x08000000


def no_window_kwargs(platform: str | None = None) -> dict:
    """No Windows, impede que cada processo filho abra uma janela de console por cima do jogo/app."""
    return {"creationflags": CREATE_NO_WINDOW} if (platform or sys.platform) == "win32" else {}
