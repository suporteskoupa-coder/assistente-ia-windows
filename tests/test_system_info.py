"""Dados reais do PC para o núcleo: CPU, RAM, placa de vídeo e jogo aberto."""
from pathlib import Path

from tests.tools.helpers import make_cfg, make_steam
from ultron.system_info import SystemInfo, game_dirs, parse_nvidia_smi


def test_parse_nvidia_smi():
    assert parse_nvidia_smi("37, 2210, 8192\n") == {"gpu": 37.0, "vram": round(2210 / 8192 * 100, 1)}
    assert parse_nvidia_smi("") is None
    assert parse_nvidia_smi("[N/A], [N/A], [N/A]") is None


def test_game_dirs_maps_installdir_to_name(tmp_path):
    root = make_steam(tmp_path / "Steam", {str(tmp_path / "Steam"): [("730", "Counter-Strike 2")],
                                           str(tmp_path / "D"): [("367520", "Hollow Knight")]})
    dirs = game_dirs(root)
    assert dirs[(tmp_path / "Steam" / "steamapps" / "common" / "Counter-Strike 2").resolve()] == "Counter-Strike 2"
    assert dirs[(tmp_path / "D" / "steamapps" / "common" / "Hollow Knight").resolve()] == "Hollow Knight"


def info(tmp_path, procs, smi="20, 1000, 8000"):
    root = make_steam(tmp_path / "Steam", {str(tmp_path / "Steam"): [("730", "Counter-Strike 2")]})
    cfg = make_cfg(tmp_path, steam_root=root)
    clock = [0.0]
    si = SystemInfo(cfg, cpu=lambda: 12.5, ram=lambda: 48.0, smi=lambda: smi, processes=lambda: procs,
                    clock=lambda: clock[0])
    return si, root, clock


def test_snapshot_without_game(tmp_path):
    si, _, _ = info(tmp_path, ["C:/Windows/explorer.exe", None])
    s = si.snapshot()
    assert s == {"cpu": 12.5, "ram": 48.0, "gpu": 20.0, "vram": 12.5, "game": None}


def test_snapshot_detects_steam_game(tmp_path):
    root = tmp_path / "Steam"
    exe = str(root / "steamapps" / "common" / "Counter-Strike 2" / "game" / "bin" / "cs2.exe")
    si, _, _ = info(tmp_path, [exe])
    assert si.snapshot()["game"] == "Counter-Strike 2"


def test_no_nvidia(tmp_path):
    si, _, _ = info(tmp_path, [], smi=None)
    s = si.snapshot()
    assert s["gpu"] is None and s["vram"] is None


def test_expensive_parts_are_cached(tmp_path):
    calls = {"smi": 0, "proc": 0}
    root = make_steam(tmp_path / "Steam", {str(tmp_path / "Steam"): [("730", "CS")]})
    cfg = make_cfg(tmp_path, steam_root=root)
    clock = [0.0]

    def smi():
        calls["smi"] += 1
        return "1, 1, 2"

    def procs():
        calls["proc"] += 1
        return []

    si = SystemInfo(cfg, cpu=lambda: 1, ram=lambda: 1, smi=smi, processes=procs, clock=lambda: clock[0])
    si.snapshot(); si.snapshot()
    assert calls == {"smi": 1, "proc": 1}
    clock[0] = 6
    si.snapshot()
    assert calls == {"smi": 2, "proc": 2}


def test_system_endpoint(tmp_path):
    from fastapi.testclient import TestClient
    from tests.fakes import FakeBrain
    from ultron.chats import ChatStore
    from ultron.confirm import ConfirmBroker
    from ultron.memory import Vault
    from ultron.server import create_app
    from ultron.service import Ultron
    cfg = make_cfg(tmp_path)
    v = Vault(cfg.vault)
    v.ensure()
    hud = tmp_path / "hud"
    hud.mkdir()
    (hud / "index.html").write_text("x")
    si, _, _ = info(tmp_path, [])
    u = Ultron(cfg, ChatStore(cfg.db_path), v, {"claude": FakeBrain()}, ConfirmBroker())
    with TestClient(create_app(u, ConfirmBroker(), hud, system=si)) as c:
        assert c.get("/api/system").json()["cpu"] == 12.5
