"""Descobrir e abrir jogos instalados na Steam."""
from __future__ import annotations

import difflib
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ultron.config import Config
from ultron.tools.apps import Launcher

KV_RE = re.compile(r'"([^"]+)"\s+"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Game:
    appid: str
    name: str


def find_steam_root() -> Path | None:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                p = Path(winreg.QueryValueEx(k, "SteamPath")[0])
                if p.exists():
                    return p
        except OSError:
            pass
    for p in (Path("C:/Program Files (x86)/Steam"), Path("C:/Program Files/Steam")):
        if p.exists():
            return p
    return None


def _libraries(root: Path) -> list[Path]:
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for key, value in KV_RE.findall(vdf.read_text(encoding="utf-8", errors="replace")):
            if key == "path":
                p = Path(value.replace("\\\\", "\\"))
                if p not in libs:
                    libs.append(p)
    return libs


def installed_games(steam_root: Path) -> list[Game]:
    games: dict[str, Game] = {}
    for lib in _libraries(Path(steam_root)):
        for acf in sorted((lib / "steamapps").glob("appmanifest_*.acf")):
            data = dict(KV_RE.findall(acf.read_text(encoding="utf-8", errors="replace")))
            if "appid" in data and "name" in data:
                games[data["appid"]] = Game(data["appid"], data["name"])
    return list(games.values())


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _word_prefix(q_words: list[str], n_words: list[str]) -> bool:
    """Cada palavra da busca é começo de uma palavra do nome, na ordem ("dark souls" → "Dark Souls III")."""
    i = 0
    for w in n_words:
        if i < len(q_words) and w.startswith(q_words[i]):
            i += 1
    return i == len(q_words)


def match_game(games: list[Game], query: str) -> Game | list[Game]:
    """Um jogo só quando o casamento é forte e único. Senão, lista de sugestões (nunca abre o errado)."""
    q = _norm(query)
    if not q:
        return []
    for g in games:
        if _norm(g.name) == q:
            return g
    q_words = q.split()
    strong, weak = [], []
    for g in games:
        n = _norm(g.name)
        n_words = n.split()
        initials = "".join(w[0] for w in n_words)
        if (len(q) >= 2 and " " not in q and initials.startswith(q)) or (len(q) >= 3 and _word_prefix(q_words, n_words)):
            strong.append(g)
        elif (len(q) >= 3 and any(w.startswith(q) or q in w for w in n_words)) or \
                difflib.SequenceMatcher(None, q, n).ratio() >= 0.6:
            weak.append(g)
    if len(strong) == 1:
        return strong[0]
    return (strong or weak)[:5]


def open_game(cfg: Config, query: str, launch: Launcher) -> str:
    root = cfg.steam_root or find_steam_root()
    if root is None:
        return "ERRO: não achei a Steam. Defina [steam] root no ultron.toml."
    res = match_game(installed_games(root), query)
    if isinstance(res, Game):
        launch(f"steam://rungameid/{res.appid}")
        return f"Abrindo {res.name}."
    if not res:
        return f"Não encontrei '{query}' nos jogos instalados da Steam."
    return "Não abri nada. Você quis dizer: " + ", ".join(g.name for g in res) + "?"
