"""Cérebro local: modelo no Ollama com laço de ferramentas próprio.

Só usa as ferramentas do Ultron marcadas como locais. Sem terminal, sem web.
Ações que pedem confirmação passam pelo ConfirmBroker antes de rodar.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ultron.chats import Message
from ultron.config import Config
from ultron.confirm import ConfirmBroker
from ultron.events import Event
from ultron.tools.registry import Registry

MAX_STEPS = 8
SCREEN_TOOL = "ver_tela"


class OllamaBrain:
    name = "ollama"

    def __init__(self, cfg: Config, registry: Registry, broker: ConfirmBroker, http: httpx.AsyncClient,
                 capturer=None):
        self.cfg = cfg
        self.registry = registry
        self.broker = broker
        self.http = http
        self.capturer = capturer
        self._local = {t.name: t for t in registry.local()}

    def _can_see(self) -> bool:
        return bool(self.capturer and self.cfg.screen_enabled and self.cfg.ollama_vision_model)

    def _tools(self) -> list[dict]:
        tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}}
                 for t in self._local.values()]
        if self._can_see():
            tools.append({"type": "function", "function": {
                "name": SCREEN_TOOL,
                "description": "Olha a tela do usuário e responde uma pergunta sobre ela. Use só quando ele pedir.",
                "parameters": {"type": "object", "properties": {"pergunta": {
                    "type": "string", "description": "O que procurar na tela"}}, "required": ["pergunta"]},
            }})
        return tools

    async def _see(self, pergunta: str) -> str:
        """O modelo de visão descreve a tela; o modelo de conversa recebe só o texto."""
        try:
            shot = await self.capturer.capture()
        except Exception as e:
            return f"ERRO: não consegui capturar a tela: {e}"
        model = self.cfg.ollama_vision_model
        prompt = ("Descreva o que há nesta tela de computador que ajude a responder: "
                  f"{pergunta}\nTranscreva exatamente qualquer mensagem de erro ou texto importante.")
        try:
            r = await self.http.post(
                f"{self.cfg.ollama_url.rstrip('/')}/api/chat",
                json={"model": model, "messages": [{"role": "user", "content": prompt, "images": [shot.png_b64]}],
                      "stream": False, "options": {"num_ctx": self.cfg.ollama_ctx}},
                timeout=300,
            )
        except httpx.HTTPError as e:
            return f"ERRO: falha ao falar com o Ollama: {e}"
        if r.status_code == 404:
            return f"ERRO: o modelo de visão '{model}' não está baixado. Rode: ollama pull {model}"
        if r.status_code >= 300:
            return f"ERRO: Ollama respondeu {r.status_code}"
        return "Descrição da tela: " + r.json().get("message", {}).get("content", "")

    async def _chat(self, messages: list[dict]) -> dict:
        r = await self.http.post(
            f"{self.cfg.ollama_url.rstrip('/')}/api/chat",
            json={"model": self.cfg.ollama_model, "messages": messages, "tools": self._tools(),
                  "stream": False, "options": {"num_ctx": self.cfg.ollama_ctx}},
            timeout=300,
        )
        if r.status_code == 404:
            raise LookupError(f"Modelo '{self.cfg.ollama_model}' não está baixado. Rode: ollama pull {self.cfg.ollama_model}")
        r.raise_for_status()
        return r.json().get("message", {})

    async def _run_tool(self, name: str, args: dict, meta: dict | None = None) -> str:
        if name == SCREEN_TOOL and self._can_see():
            return await self._see(str(args.get("pergunta", "")))
        tool = self._local.get(name)
        if tool is None:
            return f"ERRO: ferramenta '{name}' não está disponível no modo local."
        if tool.confirm:
            allow, edited = await self.broker.request_detail(name, args, meta)
            if not allow:
                return "Negado pelo usuário."
            if edited:
                args = edited
        return await self.registry.call(name, args)

    async def send(self, session_id: str | None, history: list[Message], text: str, system: str,
                   chat_ref: str | None = None) -> AsyncIterator[Event]:
        # pedidos do chat do Discord: a confirmação vai para a DM do criador
        meta = {"remote": True} if chat_ref and "Discord (celular)" in chat_ref else None
        messages = [{"role": "system", "content": system}]
        messages += [{"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant")]
        messages.append({"role": "user", "content": text})

        for _ in range(MAX_STEPS + 1):
            try:
                msg = await self._chat(messages)
            except httpx.ConnectError:
                yield Event("error", "Ollama não está rodando. Abra o Ollama e tente de novo.")
                return
            except LookupError as e:
                yield Event("error", str(e))
                return
            except httpx.HTTPError as e:
                yield Event("error", f"Erro no Ollama: {e}")
                return

            calls = msg.get("tool_calls") or []
            if not calls:
                from ultron.server_replies import strip_thinking

                content = strip_thinking(msg.get("content") or "")  # Qwen3 às vezes manda o raciocínio junto
                if content:
                    yield Event("text", content)
                yield Event("done")
                return

            if sum(1 for m in messages if m["role"] == "tool") >= MAX_STEPS:
                yield Event("error", "Parei: o modelo local passou do limite de 8 passos com ferramentas.")
                return

            messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                yield Event("tool", data={"name": name, "input": args})
                result = await self._run_tool(name, args, meta)
                messages.append({"role": "tool", "content": result, "tool_name": name})

        yield Event("error", "Parei: o modelo local passou do limite de 8 passos com ferramentas.")
