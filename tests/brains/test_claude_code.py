import json
import stat
import sys
from pathlib import Path

import pytest

from tests.tools.helpers import make_cfg
from ultron.brains.claude_code import ClaudeCodeBrain

FIX = Path(__file__).parent.parent / "fixtures"


def fake_bin(tmp_path: Path) -> str:
    p = tmp_path / "claude"
    p.write_text(f"#!/bin/sh\nexec {sys.executable} {FIX / 'fake_claude.py'} \"$@\"\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def brain(tmp_path, **kw):
    cfg = make_cfg(tmp_path, claude_bin=kw.pop("bin", None) or fake_bin(tmp_path))
    return ClaudeCodeBrain(cfg, tmp_path / "mcp.json", ["mcp__ultron__abrir_jogo", "Read", "Bash(git status)"], tmp_path)


async def collect(it):
    return [e async for e in it]


def test_build_args_without_session(tmp_path):
    args = brain(tmp_path).build_args(None, tmp_path / "sys.txt")
    assert args[1:3] == ["-p", "--output-format"] or "-p" in args
    assert "--resume" not in args
    i = args.index("--allowedTools")
    assert args[i + 1] == "mcp__ultron__abrir_jogo,Read,Bash(git status)"
    assert args[args.index("--permission-prompt-tool") + 1] == "mcp__ultron__aprovar_permissao"
    assert args[args.index("--mcp-config") + 1] == str(tmp_path / "mcp.json")
    assert "--strict-mcp-config" in args
    assert args[args.index("--append-system-prompt-file") + 1] == str(tmp_path / "sys.txt")


def test_build_args_with_session(tmp_path):
    args = brain(tmp_path).build_args("abc", tmp_path / "s.txt")
    assert args[args.index("--resume") + 1] == "abc"


async def test_stream_maps_events_and_sends_text_by_stdin(tmp_path, monkeypatch):
    log = tmp_path / "log.json"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    evs = await collect(brain(tmp_path).send(None, [], "oi & del *", "Você é o Ultron."))
    assert [e.kind for e in evs] == ["session", "text", "done"]
    assert evs[0].data["id"] == "11111111-2222-3333-4444-555555555555"
    assert evs[1].text == "oi"
    sent = json.loads(log.read_text())
    assert sent["stdin"] == "oi & del *"
    assert "oi & del *" not in sent["args"]


async def test_tool_events_and_error_result(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "claude_tool_stream.jsonl")
    evs = await collect(brain(tmp_path).send("sess-2", [], "abre o cs", ""))
    kinds = [e.kind for e in evs]
    assert kinds == ["session", "tool", "text", "error"]
    assert evs[1].data == {"name": "abrir_jogo", "input": {"nome": "cs"}}
    assert "Limite" in evs[3].text


async def test_missing_binary(tmp_path):
    evs = await collect(brain(tmp_path, bin=str(tmp_path / "nao-existe")).send(None, [], "oi", ""))
    assert len(evs) == 1 and evs[0].kind == "error"
    assert "Claude Code não encontrado" in evs[0].text


async def test_nonzero_exit_reports_stderr(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FIXTURE", "empty.jsonl")
    (FIX / "empty.jsonl").exists() or (FIX / "empty.jsonl").write_text("")
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "1")
    evs = await collect(brain(tmp_path).send(None, [], "oi", ""))
    assert evs[-1].kind == "error" and "deu ruim" in evs[-1].text


async def test_child_does_not_inherit_parent_claude_session(tmp_path, monkeypatch):
    log = tmp_path / "log.json"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "pai")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_MODEL", "fica")
    await collect(brain(tmp_path).send(None, [], "oi", ""))
    env = json.loads(log.read_text())["env"]
    assert "CLAUDE_CODE_SESSION_ID" not in env and "CLAUDECODE" not in env
    assert env["ANTHROPIC_MODEL"] == "fica"


def test_system_prompt_is_rendered_fresh_every_message(tmp_path):
    # sem isto, o Claude Code reaproveita o prompt da 1ª mensagem para sempre (hora, memória e identidade velhas)
    args = brain(tmp_path).build_args("abc", tmp_path / "s.txt")
    assert args[args.index("--system-prompt-snapshot") + 1] == "off"
