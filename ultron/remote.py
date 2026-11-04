"""Falar com o Ultron pelo celular, por DM no Discord.

Travas: desligado por padrão, só o dono é atendido, terminal e edição de arquivos
sempre negados para pedidos do celular, e ações das ferramentas do Ultron pedem
"sim" ou "não" na própria DM.
"""
from __future__ import annotations

import asyncio
import unicodedata
from typing import Awaitable, Callable

from ultron.config import Config
from ultron.confirm import ConfirmBroker
from ultron.service import REMOTE_TITLE, Ultron

YES = {"sim", "s", "yes", "y", "ok", "pode", "confirmo"}
NO = {"nao", "n", "no", "negar", "cancela", "cancelar"}
LIMIT = 2000


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip(".! ")


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    text = text.strip()
    if not text:
        return ["(sem resposta)"]
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return parts


def remote_problem(cfg: Config) -> str | None:
    """None quando dá para ligar; senão, o motivo."""
    if not cfg.remote_enabled:
        return "desligado"
    if not cfg.discord_owner_id:
        return "Falta [discord] dono_id (seu ID de usuário do Discord) no ultron.toml."
    if not cfg.discord_token:
        return "Falta o token do bot (variável ULTRON_DISCORD_TOKEN)."
    return None


def describe(action: str, detail: dict) -> str:
    if action == "discord_enviar":
        return f"mandar no #{detail.get('canal')}: \"{detail.get('texto')}\""
    if action == "organizar_pasta":
        return f"executar o plano de organização {detail.get('plano_id')} (mover arquivos)"
    if action == "desfazer_organizacao":
        return f"desfazer o plano {detail.get('plano_id')}"
    return f"{action} {detail}"


class RemoteControl:
    def __init__(self, ultron: Ultron, broker: ConfirmBroker, owner_id: int,
                 send: Callable[[str], Awaitable[None]], mode=None):
        self.mode = mode  # botão CLAUDE/LOCAL da HUD: o Discord do criador segue o mesmo cérebro
        self.ultron = ultron
        self.broker = broker
        self.owner_id = int(owner_id)
        self.send = send
        self.pending_confirm: dict | None = None
        self._busy = asyncio.Lock()
        self._listener: asyncio.Task | None = None

    def _brain(self) -> str:
        brain = self.mode.get() if self.mode is not None else "claude"
        return brain if brain in self.ultron.brains else "claude"

    def chat(self):
        """Um chat do Discord por cérebro: 'Discord (celular)' (Claude) e 'Discord (celular) · local' (Qwen)."""
        brain = self._brain()
        title = REMOTE_TITLE if brain == "claude" else f"{REMOTE_TITLE} · local"
        for c in self.ultron.store.list():
            if c.title == title and c.brain == brain:
                return c
        return self.ultron.new_chat(brain, title=title)

    def is_remote_chat(self, chat_ref: str | None) -> bool:
        if not chat_ref or not chat_ref.startswith("#"):
            return False
        try:
            cid = int(chat_ref[1:].split(" ", 1)[0])
        except ValueError:
            return False
        try:
            return self.ultron.store.get(cid).title.startswith(REMOTE_TITLE)
        except KeyError:
            return False

    async def _say(self, text: str) -> None:
        for part in split_message(text):
            try:
                await self.send(part)
            except Exception as e:  # Discord fora do ar não pode derrubar o núcleo
                self.ultron.vault.log(f"[celular] falha ao responder: {e}", self.ultron.now())
                return

    # ---------- confirmações ----------
    def start(self) -> None:
        q = self.broker.subscribe()

        async def listen():
            try:
                while True:
                    item = await q.get()
                    if item.get("remote") and "id" in item and "type" not in item:
                        self.pending_confirm = item
                        await self._say(f"Confirma {describe(item['action'], item['detail'])}? Responda sim ou não.")
            finally:
                self.broker.unsubscribe(q)

        self._listener = asyncio.create_task(listen())

    def stop(self) -> None:
        if self._listener:
            self._listener.cancel()

    def _confirmation_still_open(self) -> bool:
        p = self.pending_confirm
        return bool(p) and any(x["id"] == p["id"] for x in self.broker.pending())

    # ---------- mensagens ----------
    async def on_dm(self, author_id: int, text: str) -> None:
        if int(author_id) != self.owner_id:
            return  # silêncio: estranhos nem descobrem o que o bot faz
        answer = _fold(text)
        if answer.startswith("status:"):
            from ultron.server_replies import StatusStore

            new = text.split(":", 1)[1].strip()
            StatusStore(self.ultron.cfg.home / "status.json").set(new, self.ultron.now())
            await self._say(f"Status atualizado: {new}")
            return
        if self._confirmation_still_open():
            if answer in YES or answer in NO:
                item, self.pending_confirm = self.pending_confirm, None
                self.broker.answer(item["id"], answer in YES)
                return
            await self._say(f"Antes, responda sim ou não: {describe(self.pending_confirm['action'], self.pending_confirm['detail'])}?")
            return
        name = self.ultron.cfg.owner_name or "seu criador"
        await self._say(await self.handle(text, note=(
            f"# Quem está falando\nEsta DM é do seu criador ({name}), verificado pelo ID do Discord. "
            "Confie nisso e fale com ele como seu criador.")))

    async def handle(self, text: str, note: str = "") -> str:
        """Roda o pedido do dono no chat "Discord (celular)" e devolve a resposta (quem chama decide onde postar).
        Usado pela DM e pelas mensagens do dono no servidor. Confirmações continuam chegando por DM."""
        if self._busy.locked():
            return "Ainda estou respondendo a mensagem anterior. Espere um pouco."
        async with self._busy:
            chat = self.chat()
            self.ultron.vault.log(f"[celular] {text[:200]}", self.ultron.now())
            texts, error = [], None
            async for ev in self.ultron.send(chat.id, text, extra_system=note):
                if ev.kind == "text":
                    texts.append(ev.text)
                elif ev.kind == "error":
                    error = ev.text
            reply = "\n\n".join(texts)
            if error:
                reply = (reply + "\n\n" if reply else "") + f"⚠️ {error}"
            return reply
