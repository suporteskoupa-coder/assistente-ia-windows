"""Servidor MCP mínimo (JSON-RPC por stdio) que expõe as ferramentas do Ultron ao Claude Code.

Implementa só o necessário: initialize, ping, tools/list e tools/call.
Também expõe `aprovar_permissao`, usada pelo Claude Code (--permission-prompt-tool)
para pedir confirmação ao usuário pela HUD.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

from ultron.tools.registry import Registry, obj

PERMISSION_TOOL = "aprovar_permissao"
SCREEN_TOOL = "ver_tela"
DEFAULT_PROTOCOL = "2025-06-18"


class McpServer:
    def __init__(self, registry: Registry, core_url: str, core: httpx.AsyncClient, token: str = ""):
        self.registry = registry
        self.token = token
        self.core_url = core_url.rstrip("/")
        self.core = core

    def _tools(self) -> list[dict]:
        out = [{"name": t.name, "description": t.description, "inputSchema": t.schema} for t in self.registry.all()]
        out.append({
            "name": SCREEN_TOOL,
            "description": "Tira um print do monitor principal do usuário e mostra a imagem. "
                           "Use só quando o usuário pedir para olhar a tela.",
            "inputSchema": obj(),
        })
        out.append({
            "name": PERMISSION_TOOL,
            "description": "Uso interno: pede ao usuário, pela HUD, permissão para uma ação.",
            "inputSchema": obj({"tool_name": {"type": "string"}, "input": {"type": "object"},
                                "tool_use_id": {"type": "string"}}, ["tool_name", "input"]),
        })
        return out

    async def _permission(self, args: dict) -> str:
        tool_input = args.get("input") or {}
        try:
            r = await self.core.post(f"{self.core_url}/api/permission",
                                     json={"tool_name": args.get("tool_name", ""), "input": tool_input,
                                           "chat": os.environ.get("ULTRON_CHAT")},
                                     headers={"X-Ultron-Token": self.token}, timeout=130)
            data = r.json()
            allow = r.status_code < 300 and data.get("allow") is True
        except (httpx.HTTPError, ValueError):
            allow, data = False, {}
        if allow:
            return json.dumps({"behavior": "allow", "updatedInput": data.get("input") or tool_input})
        return json.dumps({"behavior": "deny", "message": "Negado pelo usuário (ou sem resposta da HUD)."})

    async def _screen(self) -> list[dict]:
        try:
            r = await self.core.post(f"{self.core_url}/api/screenshot",
                                     headers={"X-Ultron-Token": self.token}, timeout=30)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            return [{"type": "text", "text": f"ERRO: o Ultron não respondeu ao pedido de print ({e})."}]
        if r.status_code >= 300:
            return [{"type": "text", "text": f"ERRO: {data.get('detail', r.status_code)}"}]
        return [
            {"type": "image", "data": data["png_b64"], "mimeType": "image/png"},
            {"type": "text", "text": f"Print do monitor principal ({data['width']}x{data['height']})."},
        ]

    async def handle(self, msg: dict) -> dict | None:
        mid = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}
        if mid is None:
            return None  # notificação
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ultron", "version": "0.1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self._tools()}
        elif method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments") or {}
            if name == SCREEN_TOOL:
                content = await self._screen()
                result = {"content": content, "isError": content[0].get("text", "").startswith("ERRO")}
            else:
                text = await (self._permission(args) if name == PERMISSION_TOOL else self.registry.call(name, args))
                result = {"content": [{"type": "text", "text": text}], "isError": text.startswith("ERRO")}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Método não suportado: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    async def serve_stdio(self) -> None:
        loop = asyncio.get_running_loop()
        out = sys.stdout.buffer
        while True:
            line = await loop.run_in_executor(None, sys.stdin.buffer.readline)
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            reply = await self.handle(msg)
            if reply is not None:
                out.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
                out.flush()


def main() -> None:
    from ultron.config import load_config
    from ultron.memory import Vault
    from ultron.tools.apps import default_launcher
    from ultron.tools.registry import build_registry

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()
    cfg = load_config(Path(a.config))
    vault = Vault(cfg.vault)
    vault.ensure()

    async def run():
        async with httpx.AsyncClient() as http:
            reg = build_registry(cfg, vault, default_launcher, http, chat_source=os.environ.get("ULTRON_CHAT"))
            token = os.environ.get("ULTRON_TOKEN", "")
            await McpServer(reg, f"http://127.0.0.1:{cfg.core_port}", http, token).serve_stdio()

    asyncio.run(run())


if __name__ == "__main__":
    main()
