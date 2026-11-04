"""Registro único de ferramentas, usado pelo servidor MCP (Claude) e pelo cérebro local."""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from ultron.config import Config
from ultron.memory import Vault
from ultron.tools.apps import Launcher


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    func: Callable[..., Awaitable[str] | str]
    confirm: bool = False
    local: bool = True


def obj(props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or []}


def s(desc: str, **extra) -> dict:
    return {"type": "string", "description": desc, **extra}


class Registry:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def local(self) -> list[Tool]:
        return [t for t in self._tools.values() if t.local]

    def get(self, name: str) -> Tool:
        return self._tools[name]

    async def call(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"ERRO: ferramenta desconhecida: {name}"
        missing = [k for k in tool.schema.get("required", []) if k not in (args or {})]
        if missing:
            return f"ERRO: faltam argumentos: {', '.join(missing)}"
        try:
            out = tool.func(**(args or {}))
            if inspect.isawaitable(out):
                out = await out
            return str(out)
        except Exception as e:  # erro de ferramenta volta como texto para o cérebro
            return f"ERRO: {e}"


def confirm_tool_names(reg: Registry) -> list[str]:
    return [t.name for t in reg.all() if t.confirm]


def build_registry(cfg: Config, vault: Vault, launch: Launcher, http: httpx.AsyncClient,
                   chat_source: str | None = None, reminders=None, now=None) -> Registry:
    from datetime import datetime

    from ultron.reminders import ReminderStore, describe_when, parse_when
    from ultron.tools import apps, discord, folders, steam, vault_tools

    now = now or datetime.now
    _store = [reminders]

    def store():
        if _store[0] is None:
            _store[0] = ReminderStore(cfg.db_path)
        return _store[0]

    def lembrete_criar(texto: str, quando: str, repetir: str | None = None) -> str:
        r = store().create(texto, parse_when(quando), repetir or None, now())
        rep = f", repetindo ({r.repeat})" if r.repeat else ""
        return f"Lembrete #{r.id} marcado para {describe_when(r.due_dt)}{rep}: {r.text}"

    def lembrete_listar() -> str:
        items = store().list_pending()
        if not items:
            return "Nenhum lembrete pendente."
        return "\n".join(f"#{r.id} {describe_when(r.due_dt)}{f' ({r.repeat})' if r.repeat else ''}: {r.text}" for r in items)

    def definir_status(texto: str) -> str:
        from ultron.server_replies import StatusStore

        StatusStore(cfg.home / "status.json").set(texto, now())
        return f"Status atualizado: {texto}"

    def lembrete_cancelar(id: int) -> str:
        return f"Lembrete #{id} cancelado." if store().cancel(int(id)) else f"ERRO: lembrete #{id} não encontrado ou já disparado."

    def listar(caminho: str) -> str:
        from pathlib import Path
        items = folders.list_folder(Path(caminho).expanduser())
        lines = [f"{'[pasta] ' if i['is_dir'] else ''}{i['name']}  {i['size']} B  {i['modified']}" for i in items]
        return "\n".join(lines) or "(pasta vazia)"

    def planejar(caminho: str) -> str:
        from pathlib import Path
        return folders.describe_plan(folders.plan_organize(cfg.home, Path(caminho).expanduser()))

    tools = [
        Tool("abrir_app", "Abre um app da lista configurada pelo usuário.",
             obj({"nome": s("Apelido do app, ex.: vscode")}, ["nome"]),
             lambda nome: apps.open_app(cfg, nome, launch)),
        Tool("abrir_jogo", "Abre um jogo instalado na Steam pelo nome ou abreviação.",
             obj({"nome": s("Nome do jogo, ex.: cs, hollow knight")}, ["nome"]),
             lambda nome: steam.open_game(cfg, nome, launch)),
        Tool("ativar_modo", "Ativa um modo (conjunto de apps e sites), ex.: trabalho, jogo.",
             obj({"nome": s("Nome do modo")}, ["nome"]),
             lambda nome: apps.activate_mode(cfg, nome, launch)),
        Tool("listar_pasta", "Lista arquivos e pastas de um caminho do PC.",
             obj({"caminho": s("Caminho da pasta, ex.: C:/Users/voce/Downloads")}, ["caminho"]),
             listar),
        Tool("planejar_organizacao", "Monta um plano para organizar uma pasta por tipo de arquivo. Não move nada; devolve o id do plano.",
             obj({"caminho": s("Pasta a organizar")}, ["caminho"]), planejar),
        Tool("organizar_pasta", "Executa um plano de organização já criado. Move arquivos, nunca apaga.",
             obj({"plano_id": s("Id devolvido por planejar_organizacao")}, ["plano_id"]),
             lambda plano_id: folders.execute_plan(cfg.home, plano_id), confirm=True),
        Tool("desfazer_organizacao", "Desfaz um plano de organização executado.",
             obj({"plano_id": s("Id do plano")}, ["plano_id"]),
             lambda plano_id: folders.undo_plan(cfg.home, plano_id), confirm=True),
        *vault_tools.tools(vault, chat_source),
        Tool("lembrete_criar", "Cria um lembrete. 'quando' é data e hora local no formato AAAA-MM-DD HH:MM.",
             obj({"texto": s("O que lembrar"), "quando": s("AAAA-MM-DD HH:MM"),
                  "repetir": s("Opcional: diario ou semanal", enum=["diario", "semanal"])}, ["texto", "quando"]),
             lembrete_criar),
        Tool("lembrete_listar", "Lista os lembretes pendentes.", obj(), lembrete_listar),
        Tool("lembrete_cancelar", "Cancela um lembrete pelo número.",
             obj({"id": {"type": "integer", "description": "Número do lembrete"}}, ["id"]), lembrete_cancelar),
        Tool("definir_status", "Define o status público do usuário, usado quando o Ultron responde por ele no servidor "
             "do Discord (ex.: 'jogando até 23h', 'livre depois das 21h').",
             obj({"texto": s("O status")}, ["texto"]), definir_status),
        Tool("discord_enviar", "Envia mensagem num canal do Discord pelo bot do Ultron.",
             obj({"canal": s("Apelido do canal, ex.: geral"), "texto": s("Mensagem")}, ["canal", "texto"]),
             lambda canal, texto: discord.discord_send(cfg, canal, texto, http), confirm=True),
    ]
    return Registry(tools)
