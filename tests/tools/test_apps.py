import pytest

from tests.tools.helpers import make_cfg
from ultron.tools.apps import activate_mode, open_app


def test_open_app_launches_configured_target(tmp_path):
    calls = []
    msg = open_app(make_cfg(tmp_path), "vscode", calls.append)
    assert calls == ["code"]
    assert "vscode" in msg


def test_open_app_unknown_lists_apps(tmp_path):
    calls = []
    msg = open_app(make_cfg(tmp_path), "photoshop", calls.append)
    assert calls == []
    assert "vscode" in msg and "spotify" in msg


def test_open_app_is_case_insensitive(tmp_path):
    calls = []
    open_app(make_cfg(tmp_path), "VSCode", calls.append)
    assert calls == ["code"]


def test_activate_mode_launches_apps_then_urls(tmp_path):
    calls = []
    activate_mode(make_cfg(tmp_path), "trabalho", calls.append)
    assert calls == ["code", "spotify:", "https://github.com"]


def test_activate_unknown_mode(tmp_path):
    calls = []
    msg = activate_mode(make_cfg(tmp_path), "festa", calls.append)
    assert calls == [] and "trabalho" in msg
