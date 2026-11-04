"""Cérebro Claude: roda o Claude Code oficial (`claude -p`) e lê o stream-json.

O Ultron nunca toca no login do Claude; só executa o programa da Anthropic.
O texto do usuário vai pela entrada padrão (stdin), nunca como argumento,
para não ser interpretado pelo shell do Windows (.cmd).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import AsyncIterator

from ultron.chats import Message
from ultron.config import Config
from ultron.events import Event
from ultron.winproc import no_window_kwargs

MCP_PREFIX = "mcp__ultron__"
PERMISSION_TOOL = MCP_PREFIX + "aprovar_permissao"
# Variáveis que fariam o processo filho se misturar com uma sessão do Claude Code que abriu o Ultron.
INHERITED_SESSION_VARS = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                          "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_PID", "CLAUDE_CODE_REMOTE_SESSION_ID")


def mcp_config_for(base: Path, chat_ref: str | None, outdir: Path) -> Path:
    """Cópia da configuração MCP com o chat atual (ULTRON_CHAT), para a ferramenta concluir saber a fonte."""
    if not chat_ref:
        return Path(base)
    data = json.loads(Path(base).read_text(encoding="utf-8"))
    for server in data.get("mcpServers", {}).values():
        server.setdefault("env", {})["ULTRON_CHAT"] = chat_ref
    outdir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(chat_ref.encode("utf-8")).hexdigest()[:12]
    out = outdir / f"mcp-{name}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in INHERITED_SESSION_VARS}


class ClaudeCodeBrain:
    name = "claude"

    def __init__(self, cfg: Config, mcp_config_path: Path, allowed: list[str], workdir: Path):
        self.cfg = cfg
        self.mcp_config_path = Path(mcp_config_path)
        self.allowed = allowed
        self.workdir = Path(workdir)

    def build_args(self, session_id: str | None, system_file: Path, mcp_config: Path | None = None) -> list[str]:
        args = [
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--mcp-config", str(mcp_config or self.mcp_config_path),
            "--strict-mcp-config",
            "--append-system-prompt-file", str(system_file),
            # monta o prompt de novo a cada mensagem (hora, memória e quem está falando mudam)
            "--system-prompt-snapshot", "off",
            "--permission-prompt-tool", PERMISSION_TOOL,
            "--allowedTools", ",".join(self.allowed),
        ]
        if session_id:
            args += ["--resume", session_id]
        return args

    def _exe(self) -> str | None:
        return shutil.which(self.cfg.claude_bin)

    async def send(self, session_id: str | None, history: list[Message], text: str, system: str,
                   chat_ref: str | None = None) -> AsyncIterator[Event]:
        exe = self._exe()
        if exe is None:
            yield Event("error", "Claude Code não encontrado. Instale o Claude Code e rode `claude` uma vez para fazer login.")
            return
        self.workdir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", dir=self.workdir) as f:
            f.write(system)
            system_file = Path(f.name)
        mcp = mcp_config_for(self.mcp_config_path, chat_ref, self.workdir / "mcp")
        run = self._run(exe, session_id, text, system_file, mcp)
        try:
            async for ev in run:
                yield ev
        finally:
            await run.aclose()
            system_file.unlink(missing_ok=True)

    async def _run(self, exe: str, session_id: str | None, text: str, system_file: Path,
                   mcp: Path | None = None) -> AsyncIterator[Event]:
        try:
            proc = await asyncio.create_subprocess_exec(
                exe, *self.build_args(session_id, system_file, mcp),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workdir),
                env=child_env(),
                limit=16 * 1024 * 1024,
                **no_window_kwargs(),
            )
        except OSError as e:
            yield Event("error", f"Não consegui iniciar o Claude Code: {e}")
            return
        stderr_task = asyncio.create_task(proc.stderr.read())
        try:
            proc.stdin.write(text.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass  # o claude saiu cedo; o erro aparece abaixo pelo stderr/código
        try:
            finished = False
            async for raw in proc.stdout:
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                for ev in self._map(d):
                    if ev.kind in ("done", "error"):
                        finished = True
                    yield ev
            code = await proc.wait()
            err = (await stderr_task).decode("utf-8", "replace").strip()
            if not finished:
                detail = err[-500:] if err else f"código de saída {code}"
                yield Event("error", f"O Claude Code parou sem responder: {detail}")
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            stderr_task.cancel()

    @staticmethod
    def _map(d: dict) -> list[Event]:
        t = d.get("type")
        if t == "system" and d.get("subtype") == "init":
            return [Event("session", data={"id": d.get("session_id")})]
        if t == "assistant":
            out = []
            for c in d.get("message", {}).get("content", []):
                if c.get("type") == "text" and c.get("text"):
                    out.append(Event("text", c["text"]))
                elif c.get("type") == "tool_use":
                    name = c.get("name", "")
                    if name == "ToolSearch":
                        continue
                    out.append(Event("tool", data={"name": name.removeprefix(MCP_PREFIX), "input": c.get("input", {})}))
            return out
        if t == "result":
            if d.get("is_error"):
                return [Event("error", str(d.get("result") or d.get("subtype") or "erro no Claude Code"))]
            return [Event("done")]
        return []
