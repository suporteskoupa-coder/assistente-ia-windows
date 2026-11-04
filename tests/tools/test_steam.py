from tests.tools.helpers import make_cfg, make_steam
from ultron.tools.steam import Game, installed_games, match_game, open_game

GAMES = [("730", "Counter-Strike 2"), ("1938090", "Call of Duty"), ("367520", "Hollow Knight")]


def steam(tmp_path, extra=()):
    return make_steam(tmp_path / "Steam", {
        str(tmp_path / "Steam"): GAMES[:2],
        str(tmp_path / "D" / "SteamLibrary"): [GAMES[2], *extra],
    })


def test_installed_games_reads_all_libraries(tmp_path):
    games = installed_games(steam(tmp_path))
    assert sorted(g.appid for g in games) == ["1938090", "367520", "730"]


def test_match_abbreviation(tmp_path):
    games = installed_games(steam(tmp_path))
    assert match_game(games, "cs") == Game("730", "Counter-Strike 2")
    assert match_game(games, "hollow knight") == Game("367520", "Hollow Knight")


def test_match_ambiguous_returns_candidates(tmp_path):
    games = installed_games(steam(tmp_path, [("24840", "Call of Juarez")]))
    res = match_game(games, "call")
    assert isinstance(res, list)
    assert {g.name for g in res} == {"Call of Duty", "Call of Juarez"}


def test_match_none_returns_empty(tmp_path):
    games = installed_games(steam(tmp_path))
    assert match_game(games, "zelda") == []


def test_open_game_launches_steam_uri(tmp_path):
    calls = []
    msg = open_game(make_cfg(tmp_path, steam_root=steam(tmp_path)), "cs", calls.append)
    assert calls == ["steam://rungameid/730"]
    assert "Counter-Strike 2" in msg


def test_open_game_not_found_message(tmp_path):
    calls = []
    msg = open_game(make_cfg(tmp_path, steam_root=steam(tmp_path)), "zelda", calls.append)
    assert calls == [] and "não encontrei" in msg.lower()


def test_open_game_ambiguous_does_not_launch(tmp_path):
    calls = []
    cfg = make_cfg(tmp_path, steam_root=steam(tmp_path, [("24840", "Call of Juarez")]))
    msg = open_game(cfg, "call", calls.append)
    assert calls == [] and "Call of Juarez" in msg
