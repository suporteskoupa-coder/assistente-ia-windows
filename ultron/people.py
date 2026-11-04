"""Memória das pessoas que falam com o Ultron no Discord: uma nota por pessoa em
Ultron/Pessoas/<Nome> (<ID>).md.

- "Sobre" é sua: o Ultron nunca apaga.
- "O que o Ultron sabe": fatos que ele extrai sozinho, com confiança (apague uma linha para ele esquecer).
- "Pensamentos do Ultron": o diário secreto dele sobre a pessoa.
- "Conversas": as últimas 20 trocas.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ultron.memory import CONCL_RE, HUB_LINK, Conclusion, Vault

MAX_TALKS = 20
MAX_THOUGHTS = 10
ABOUT_HINT = "(escreva aqui o que o Ultron deve saber sobre esta pessoa)"
OLD_TALK = re.compile(r"^- (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) · ")
DIR = "Ultron/Pessoas"


def _one_line(s: str, limit: int) -> str:
    return " ".join(s.split())[:limit]


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


def _safe_name(nick: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\[\]#^\x00-\x1f]', " ", nick or "")
    return " ".join(name.split()).strip(" .")[:40] or "Pessoa"


@dataclass
class PersonNote:
    nicks: list[str] = field(default_factory=list)
    about: str = ABOUT_HINT
    talks: list[str] = field(default_factory=list)
    count: int = 0
    analyzed: int = 0
    facts: list[Conclusion] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)


class PeopleStore:
    def __init__(self, vault: Vault):
        self.vault = vault

    # ---------- arquivos ----------
    def _dir(self) -> Path:
        return self.vault.root / DIR

    def _existing(self, person_id: int) -> Path | None:
        d = self._dir()
        if not d.exists():
            return None
        pid = int(person_id)
        for p in d.glob("*.md"):
            if p.stem == str(pid) or p.stem.endswith(f"({pid})"):
                return p
        return None

    def _target(self, person_id: int, note: PersonNote) -> Path:
        cur = self._existing(person_id)
        if cur is not None and cur.stem != str(int(person_id)):
            return cur  # já tem nome legível: mantém (apelido novo não renomeia)
        first = note.nicks[0] if note.nicks else str(person_id)
        return self._dir() / f"{_safe_name(first)} ({int(person_id)}).md"

    def link(self, person_id: int, nick: str | None = None) -> str:
        cur = self._existing(person_id)
        stem = cur.stem if cur is not None and cur.stem != str(int(person_id)) else f"{_safe_name(nick or str(person_id))} ({int(person_id)})"
        label = nick or stem.rsplit(" (", 1)[0]
        return f"[[{stem}|{label}]]"

    # ---------- leitura e escrita ----------
    def load(self, person_id: int) -> PersonNote:
        p = self._existing(person_id)
        if p is None:
            return PersonNote()
        n = PersonNote()
        about, section, count = [], None, None
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("Interações:"):
                try:
                    count = int(line.split(":", 1)[1].strip())
                except ValueError:
                    count = None
            elif line.startswith("Última análise:"):
                try:
                    n.analyzed = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("Apelidos:"):
                n.nicks = [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
            elif line.startswith("## "):
                section = line[3:].strip().lower()
            elif section == "sobre":
                about.append(line)
            elif section == "o que o ultron sabe":
                m = CONCL_RE.match(line)
                if m:
                    n.facts.append(Conclusion(m["text"], m["conf"], int(m["seen"]), m["date"]))
            elif section == "pensamentos do ultron" and line.startswith("- "):
                n.thoughts.append(line)
            elif section == "conversas" and line.startswith("- "):
                n.talks.append(OLD_TALK.sub(r"- [[\1]] \2 · ", line))
        n.about = "\n".join(about).strip() or ABOUT_HINT
        n.count = len(n.talks) if count is None else count
        return n

    def save(self, person_id: int, n: PersonNote) -> None:
        target = self._target(person_id, n)
        facts = "\n".join(f.line().replace(" chats ·", " conversas ·") for f in n.facts)
        body = (f"# {n.nicks[0] if n.nicks else person_id}\n\n{HUB_LINK}\n\nDiscord ID: {int(person_id)}\n"
                f"Apelidos: {', '.join(n.nicks)}\nInterações: {n.count}\nÚltima análise: {n.analyzed}\n\n"
                f"## Sobre\n{n.about}\n\n## O que o Ultron sabe\n{facts}\n\n"
                f"## Pensamentos do Ultron\n" + "\n".join(n.thoughts[-MAX_THOUGHTS:]) + "\n\n"
                f"## Conversas\n" + "\n".join(n.talks[-MAX_TALKS:]) + "\n")
        old = self._existing(person_id)
        rel = target.relative_to(self.vault.root).as_posix()
        self.vault.write(rel, body)
        if old is not None and old.resolve() != target.resolve():
            old.unlink()  # nota antiga (só número) renomeada para o nome legível

    # ---------- operações ----------
    def record(self, person_id: int, nick: str, question: str, reply: str, now: datetime) -> None:
        n = self.load(person_id)
        if nick and nick not in n.nicks:
            n.nicks.append(nick)
        n.talks.append(f"- [[{now:%Y-%m-%d}]] {now:%H:%M} · {_one_line(question, 200)} → {_one_line(reply, 300)}")
        n.count += 1
        self.save(person_id, n)

    def interactions(self, person_id: int) -> int:
        return self.load(person_id).count

    def reset(self, person_id: int) -> None:
        n = self.load(person_id)
        n.count = 0
        n.analyzed = 0
        self.save(person_id, n)

    def due(self, person_id: int, every: int) -> bool:
        n = self.load(person_id)
        return n.count - n.analyzed >= every

    def recent_talks(self, person_id: int, k: int) -> list[str]:
        return self.load(person_id).talks[-k:]

    def known_facts(self, person_id: int) -> str:
        return "\n".join(f.line() for f in self.load(person_id).facts) or "(nenhum ainda)"

    def apply_insights(self, person_id: int, ins: dict, now: datetime) -> None:
        n = self.load(person_id)
        today = now.date().isoformat()
        drop = {_fold(x) for x in ins.get("esquecer", [])}
        n.facts = [f for f in n.facts if _fold(f.text) not in drop]
        for f in ins.get("fatos", []):
            for cur in n.facts:
                if _fold(cur.text) == _fold(f["texto"]):
                    cur.seen += 1
                    cur.confidence = f["confianca"]
                    cur.date = today
                    break
            else:
                n.facts.append(Conclusion(f["texto"], f["confianca"], 1, today))
        if ins.get("pensamento"):
            n.thoughts.append(f"- [[{today}]] {ins['pensamento']}")
            n.thoughts = n.thoughts[-MAX_THOUGHTS:]
        n.analyzed = n.count
        self.save(person_id, n)

    def mark_analyzed(self, person_id: int) -> None:
        n = self.load(person_id)
        n.analyzed = n.count
        self.save(person_id, n)

    def context(self, person_id: int) -> str:
        n = self.load(person_id)
        if not n.nicks and not n.talks:
            return ""
        parts = [f"Discord ID {int(person_id)}. Apelidos já usados: {', '.join(n.nicks) or '—'}."]
        if n.about and n.about != ABOUT_HINT:
            parts.append("Sobre esta pessoa (escrito pelo seu criador): " + n.about)
        if n.facts:
            parts.append("O que você sabe sobre ela:\n" + "\n".join(f.line() for f in n.facts))
        if n.thoughts:
            parts.append("Seus últimos pensamentos sobre ela (íntimos; use como inspiração, não repita):\n"
                         + "\n".join(n.thoughts[-3:]))
        if n.talks:
            parts.append("Últimas conversas com você:\n" + "\n".join(n.talks))
        return "\n".join(parts)
