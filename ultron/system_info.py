"""Dados reais do PC para o núcleo da HUD: CPU, RAM, placa de vídeo (NVIDIA) e jogo da Steam aberto.

As partes caras (nvidia-smi e lista de processos) ficam em cache por 5 segundos.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterable

from ultron.config import Config
from ultron.tools.steam import KV_RE, _libraries, find_steam_root
from ultron.winproc import no_window_kwargs

CACHE_SECONDS = 5


def parse_nvidia_smi(out: str | None) -> dict | None:
    try:
        util, used, total = [float(x) for x in (out or "").strip().splitlines()[0].split(",")]
    except (ValueError, IndexError):
        return None
    return {"gpu": util, "vram": round(used / total * 100, 1) if total else None}


def run_nvidia_smi() -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        return subprocess.run(
            [exe, "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, **no_window_kwargs()).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def game_dirs(steam_root: Path) -> dict[Path, str]:
    """Pasta de instalação de cada jogo → nome do jogo."""
    out = {}
    for lib in _libraries(Path(steam_root)):
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            data = dict(KV_RE.findall(acf.read_text(encoding="utf-8", errors="replace")))
            if data.get("installdir") and data.get("name"):
                out[(lib / "steamapps" / "common" / data["installdir"]).resolve()] = data["name"]
    return out


def process_paths() -> Iterable[str | None]:
    import psutil

    for p in psutil.process_iter(["exe"]):
        yield p.info.get("exe")


def _cpu() -> float:
    import psutil

    return psutil.cpu_percent(interval=None)


def _ram() -> float:
    import psutil

    return psutil.virtual_memory().percent


class SystemInfo:
    def __init__(self, cfg: Config, cpu: Callable[[], float] = _cpu, ram: Callable[[], float] = _ram,
                 smi: Callable[[], str | None] = run_nvidia_smi, processes: Callable[[], Iterable] = process_paths,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self._cpu, self._ram, self._smi, self._procs, self._clock = cpu, ram, smi, processes, clock
        self._cache: dict = {}
        self._cache_at = -1e9
        self._dirs: dict[Path, str] | None = None

    def _game(self) -> str | None:
        if self._dirs is None:
            root = self.cfg.steam_root or find_steam_root()
            self._dirs = game_dirs(root) if root else {}
        if not self._dirs:
            return None
        for exe in self._procs():
            if not exe:
                continue
            path = Path(exe)
            for d, name in self._dirs.items():
                try:
                    path.resolve().relative_to(d)
                    return name
                except (ValueError, OSError):
                    continue
        return None

    def snapshot(self) -> dict:
        now = self._clock()
        if now - self._cache_at >= CACHE_SECONDS:
            gpu = parse_nvidia_smi(self._smi()) or {"gpu": None, "vram": None}
            try:
                game = self._game()
            except Exception:
                game = None
            self._cache = {**gpu, "game": game}
            self._cache_at = now
        return {"cpu": float(self._cpu()), "ram": float(self._ram()), **self._cache}
