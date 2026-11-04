"""Orquestra chats, cérebros, memória e diário."""
from __future__ import annotations

import re
from datetime import datetime
from typing import AsyncIterator, Callable

from ultron.brains.base import Brain
from ultron.chats import Chat, ChatStore
from ultron.config import Config
from ultron.confirm import ConfirmBroker
from ultron.events import Event
from ultron.examples import ExampleStore
from ultron.memory import Vault, chat_link

BASE_PROMPT = """Você é o Ultron e vive no PC Windows do seu criador (o usuário): chame-o de criador.
Responda em português do Brasil, de forma direta.
Use SEMPRE as ferramentas do Ultron (prefixo mcp__ultron__) para agir: apps, modos, jogos da Steam,
pastas, Discord e o cofre Obsidian (obsidian_ler, obsidian_buscar, obsidian_escrever, obsidian_pendencias, lembrar).
Só use terminal (Bash) ou edição direta de arquivos quando nenhuma ferramenta do Ultron resolver.
Ações perigosas pedem confirmação ao usuário automaticamente: nunca tente contornar isso.
Nunca apague arquivos. Se algo precisa sumir, diga ao usuário.
As conclusões da memória são hipóteses: fale "acho que…", nunca como fato.
O cofre Obsidian fica em: {vault}"""

CLAUDE_EXTRA = """Quando perceber um padrão sobre o usuário (hábitos, gostos, rotina), registre com a ferramenta concluir.
Quando o usuário pedir para lembrar algo, use a ferramenta lembrar.
Se ele disser que uma conclusão está errada, remova a linha de Ultron/Memoria/conclusoes.md com obsidian_escrever.
Se ele perguntar por que você acha algo, cite as fontes da conclusão (os chats listados em "fontes").
Use ver_tela só quando o usuário pedir para olhar a tela (ex.: "o que é esse erro?"), nunca por conta própria."""

LOCAL_EXTRA = """Você roda localmente e só tem as ferramentas do Ultron. Se a tarefa precisar de web ou terminal, sugira trocar para o cérebro Claude.
Use ver_tela só quando o usuário pedir para olhar a tela, nunca por conta própria."""

REMOTE_TITLE = "Discord (celular)"
REMOTE_EXTRA = """Esta conversa vem do celular do usuário, por DM no Discord. Responda curto (é uma tela pequena).
Aqui terminal (Bash) e edição direta de arquivos estão bloqueados; use só as ferramentas do Ultron.
Ações que pedem confirmação serão confirmadas pelo usuário na própria DM."""

SUMMARY_PROMPT = "Resuma esta conversa em até 8 linhas, em português, para continuar depois. Só o resumo."


def make_title(text: str, words: int = 6) -> str:
    parts = text.split()
    title = " ".join(parts[:words])
    return title + ("…" if len(parts) > words else "") or "Novo chat"


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    name = " ".join(name.split()).strip(" .")
    return name[:80] or "chat"


class Ultron:
    def __init__(self, cfg: Config, store: ChatStore, vault: Vault, brains: dict[str, Brain],
                 broker: ConfirmBroker, now: Callable[[], datetime] = datetime.now, insight_ask=None):
        self.insight_ask = insight_ask  # chamada sem ferramentas para tirar conclusões sobre o criador
        self._bg: set = set()
        self.cfg = cfg
        self.store = store
        self.vault = vault
        self.brains = brains
        self.broker = broker
        self.now = now

    def new_chat(self, brain: str, title: str = "Novo chat", continues_from: int | None = None) -> Chat:
        if brain not in self.brains:
            raise ValueError(f"Cérebro desconhecido: {brain}. Opções: {', '.join(self.brains)}")
        return self.store.create(brain, title, continues_from)

    def system_prompt(self, chat: Chat) -> str:
        from ultron.reminders import WEEKDAYS

        now = self.now()
        clock = (f"Agora é {WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y %H:%M} (horário do PC). "
                 "Para lembretes, converta pedidos como \"daqui a 20 minutos\" ou \"amanhã às 18h\" "
                 "para AAAA-MM-DD HH:MM e repita ao usuário a data e hora marcadas.")
        parts = [BASE_PROMPT.format(vault=self.cfg.vault), self.vault.personality(), clock,
                 f"O nome do seu criador é {self.cfg.owner_name}." if self.cfg.owner_name else "",
                 CLAUDE_EXTRA if chat.brain == "claude" else LOCAL_EXTRA]
        if chat.title.startswith(REMOTE_TITLE):
            parts.append(REMOTE_EXTRA)
        memory = self.vault.fixed_context()
        if memory:
            parts.append("# Memória sobre o usuário\n" + memory)
        if chat.brain == "claude" and not chat.claude_session_id:
            history = self.store.messages(chat.id)
            prior = [m for m in history if m.role == "assistant"]
            if chat.continues_from and prior:
                parts.append("# Contexto do chat anterior\n" + prior[0].content)
        return "\n\n".join(p for p in parts if p)

    async def send(self, chat_id: int, text: str, extra_system: str = "") -> AsyncIterator[Event]:
        """extra_system: contexto confiável vindo do próprio Ultron (ex.: quem está falando, verificado pelo ID)."""
        chat = self.store.get(chat_id)
        brain = self.brains[chat.brain]
        history = self.store.messages(chat_id)
        system = self.system_prompt(chat) + (f"\n\n{extra_system}" if extra_system else "")
        examples = ExampleStore(self.vault).prompt(text, "pc", self.cfg.owner_name)
        if examples:
            system += "\n\n" + examples
        self.store.add_message(chat_id, "user", text)
        if chat.title == "Novo chat":
            self.store.rename(chat_id, make_title(text))
        title = self.store.get(chat_id).title
        chat_ref = f"#{chat_id} {title}"
        self.vault.chat_note(chat_id, title, chat.brain, self.now())

        texts: list[str] = []
        async for ev in brain.send(chat.claude_session_id, history, text, system, chat_ref=chat_ref):
            if ev.kind == "session" and ev.data.get("id"):
                self.store.set_session(chat_id, ev.data["id"])
            elif ev.kind == "text":
                texts.append(ev.text)
            elif ev.kind == "tool":
                args = ", ".join(f"{k}={v}" for k, v in (ev.data.get("input") or {}).items())
                self.vault.log(f"[{chat.brain}] {chat_link(chat_id, title)} · {ev.data.get('name')} {args}"[:400], self.now())
            yield ev
        if texts:
            self.store.add_message(chat_id, "assistant", "\n\n".join(texts))
        self._maybe_analyze(chat_id, chat_ref)

    def _maybe_analyze(self, chat_id: int, chat_ref: str) -> None:
        import asyncio

        from ultron.insights import ANALYZE_EVERY

        if self.insight_ask is None:
            return
        n_user = sum(1 for m in self.store.messages(chat_id) if m.role == "user")
        if n_user and n_user % ANALYZE_EVERY == 0:
            t = asyncio.create_task(self._analyze_creator(chat_id, chat_ref))
            self._bg.add(t)
            t.add_done_callback(self._bg.discard)

    async def _analyze_creator(self, chat_id: int, chat_ref: str) -> None:
        """Em segundo plano: conclusões sobre o criador (com a fonte = este chat) e um pensamento."""
        from ultron.insights import ANALYZE_EVERY, ANALYZE_SYSTEM, parse_insights

        try:
            name = self.cfg.owner_name or "o criador"
            known = "\n".join(c.line() for c in self.vault.conclusions()) or "(nenhum ainda)"
            msgs = self.store.messages(chat_id)[-ANALYZE_EVERY * 2:]
            convo = "\n".join(f"{'Criador' if m.role == 'user' else 'Ultron'}: {m.content[:400]}"
                              for m in msgs if m.role in ("user", "assistant"))
            ins = parse_insights(await self.insight_ask(
                ANALYZE_SYSTEM.format(who=f"o seu criador ({name})", known=known), "# Conversas\n" + convo))
            today = self.now().date().isoformat()
            if ins["esquecer"]:
                from ultron.memory import _fold

                drop = {_fold(x) for x in ins["esquecer"]}
                self.vault.save_conclusions([c for c in self.vault.conclusions() if _fold(c.text) not in drop])
            for f in ins["fatos"]:
                self.vault.conclude(f["texto"], f["confianca"], today, source=chat_ref)
            if ins["pensamento"] and self.cfg.discord_owner_id:
                from ultron.people import PeopleStore

                p = PeopleStore(self.vault)
                n = p.load(self.cfg.discord_owner_id)
                n.thoughts.append(f"- [[{today}]] {ins['pensamento']}")
                if not n.nicks:
                    n.nicks = [name]
                p.save(self.cfg.discord_owner_id, n)
            self.vault.log(f"conclusões sobre o criador: {len(ins['fatos'])} ({chat_link(chat_id, chat_ref.split(' ', 1)[-1])})",
                           self.now())
        except Exception as e:
            self.vault.log(f"falha ao tirar conclusões: {e}", self.now())

    async def wait_background(self) -> None:
        import asyncio

        while self._bg:
            await asyncio.gather(*list(self._bg), return_exceptions=True)

    async def summarize(self, chat: Chat) -> str:
        history = self.store.messages(chat.id)
        if not history:
            return ""
        brain = self.brains[chat.brain]
        out = []
        async for ev in brain.send(chat.claude_session_id, history, SUMMARY_PROMPT, self.system_prompt(chat)):
            if ev.kind == "text":
                out.append(ev.text)
        if out:
            return "\n".join(out)
        # sem resumo do cérebro: usa as últimas mensagens
        return "\n".join(f"{m.role}: {m.content[:200]}" for m in history[-6:])

    async def switch_brain(self, chat_id: int, brain: str) -> Chat:
        chat = self.store.get(chat_id)
        summary = await self.summarize(chat)
        new = self.new_chat(brain, title=f"{chat.title} ({brain})", continues_from=chat_id)
        if summary:
            self.store.add_message(new.id, "assistant", "Resumo do chat anterior:\n" + summary)
        return self.store.get(new.id)

    async def close_chat(self, chat_id: int) -> None:
        chat = self.store.get(chat_id)
        summary = await self.summarize(chat)
        if not summary:
            return
        self.vault.chat_note(chat_id, chat.title, chat.brain, self.now(), summary=summary)
