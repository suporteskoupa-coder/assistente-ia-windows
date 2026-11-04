"""Captura da tela principal para o Ultron "ver" o que você está vendo.

O print fica só na memória (nunca é salvo em disco) e a janela do Ultron se esconde
durante a captura para não aparecer na imagem.
"""
from __future__ import annotations

import asyncio
import base64
import io
import time
from dataclasses import dataclass
from typing import Callable

MAX_SIDE = 1568  # maior lado que o Claude processa sem reduzir de novo


@dataclass
class Screenshot:
    png_b64: str
    width: int
    height: int


def default_grab():
    """Monitor principal como imagem do Pillow."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1])
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


class ScreenCapturer:
    def __init__(self, grab: Callable | None = None, delay: float = 0.35):
        self._grab = grab or default_grab
        self._hide: Callable[[], None] | None = None
        self._show: Callable[[], None] | None = None
        self.delay = delay

    def set_window_hooks(self, hide: Callable[[], None], show: Callable[[], None]) -> None:
        self._hide, self._show = hide, show

    def _capture_sync(self) -> Screenshot:
        if self._hide:
            self._hide()
            time.sleep(self.delay)  # dá tempo da janela sumir da tela
        try:
            img = self._grab()
        finally:
            if self._show:
                self._show()
        img = img.convert("RGB")
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return Screenshot(base64.b64encode(buf.getvalue()).decode("ascii"), img.width, img.height)

    async def capture(self) -> Screenshot:
        return await asyncio.to_thread(self._capture_sync)
