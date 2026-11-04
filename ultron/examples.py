"""Banco de exemplos de fala do Ultron (Ultron/Exemplos.md no cofre).

A cada mensagem, os exemplos mais parecidos com o que foi dito entram nas instruções como
referência de tom. O criador edita o arquivo no Obsidian e o 👍 da HUD acrescenta novos."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ultron.memory import Vault, _fold

EXAMPLES = "Ultron/Exemplos.md"
SEED = Path(__file__).with_name("exemplos_iniciais.md")
PLACES = ("pc", "servidor", "qualquer")
MAX_CHARS = 500  # por exemplo, para não pesar nas instruções

STOPWORDS = set("""a o as os um uma uns umas de do da dos das no na nos nas em por pra pro para com sem e ou
que se me te eu tu ele ela voce vc ai la aqui isso esse essa este esta meu minha seu sua mais muito ja nao sim
ultron tá ta to tô é e foi ser ter tem como qual quais quando onde quem hoje agora acha fazer faz dia
entao tipo cara mano""".split())

HEADER = """# Sua forma de falar: exemplos aprovados pelo seu criador
Use só como referência de TOM e TAMANHO. Nunca copie as frases; os fatos deles (horários, números, nomes)
são inventados. Responda ao que foi dito agora, e só diga que fez algo depois que a ferramenta confirmar."""


@dataclass
class Example:
    title: str
    place: str
    message: str
    reply: str


def _words(text: str) -> set[str]:
    # radical simples (5 letras): "lembra", "lembrete" e "lembrar" contam como a mesma palavra
    return {w[:5] for w in re.findall(r"[a-z0-9]+", _fold(text)) if len(w) > 2 and w not in STOPWORDS}


def parse(text: str) -> list[Example]:
    out: list[Example] = []
    for block in re.split(r"(?m)^## ", text)[1:]:
        title, _, body = block.partition("\n")
        fields: dict[str, list[str]] = {}
        key = None
        for line in body.splitlines():
            m = re.match(r"^(Onde|Mensagem|Ultron)\s*:\s*(.*)$", line, re.I)
            if m:
                key = m.group(1).lower()
                fields[key] = [m.group(2)]
            elif key:
                fields[key].append(line)
        msg = "\n".join(fields.get("mensagem", [])).strip()
        reply = "\n".join(fields.get("ultron", [])).strip()
        if not msg or not reply:
            continue
        place = _fold(" ".join(fields.get("onde", ["qualquer"])).strip()) or "qualquer"
        out.append(Example(title.strip(), place if place in PLACES else "qualquer", msg, reply))
    return out


def fmt(e: Example) -> str:
    return f"## {e.title}\nOnde: {e.place}\nMensagem: {e.message}\nUltron: {e.reply}\n"


class ExampleStore:
    def __init__(self, vault: Vault):
        self.vault = vault

    @property
    def path(self) -> Path:
        return self.vault.root / EXAMPLES

    def ensure(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(SEED.read_text(encoding="utf-8"), encoding="utf-8")

    def all(self) -> list[Example]:
        if not self.path.exists():
            return []
        return parse(self.path.read_text(encoding="utf-8", errors="replace"))

    def pick(self, text: str, where: str, k: int = 3) -> list[Example]:
        """Os k exemplos mais parecidos com a mensagem, do lugar certo. Completa com outros, para o tom
        estar sempre presente. A escolha é estável para a mesma mensagem."""
        pool = [e for e in self.all() if e.place in (where, "qualquer")]
        if not pool:
            return []
        q = _words(text)
        scored = []
        for i, e in enumerate(pool):
            ew = _words(e.message) | _words(e.title)
            score = len(q & ew) / (1 + len(ew) ** 0.5) if q else 0.0
            scored.append((score, i, e))
        best = [e for s, _, e in sorted(scored, key=lambda t: (-t[0], t[1])) if s > 0][:k]
        rest = [e for e in pool if e not in best]
        random.Random(_fold(text)).shuffle(rest)
        return best + rest[: max(0, k - len(best))]

    def prompt(self, text: str, where: str, creator: str = "", k: int = 3) -> str:
        chosen = self.pick(text, where, k)
        if not chosen:
            return ""
        name = creator or "criador"
        lines = [HEADER]
        for e in chosen:
            lines.append(f"- Mensagem: {e.message[:200]}\n  Ultron: {e.reply[:MAX_CHARS]}".replace("{criador}", name))
        return "\n".join(lines)

    def add(self, message: str, reply: str, where: str = "pc", now: datetime | None = None) -> Example:
        self.ensure()
        now = now or datetime.now()
        msg = " ".join(message.split())[:300]
        # linhas que pareceriam um título ou campo novo ganham um espaço na frente
        safe = "\n".join(" " + ln if re.match(r"^(##|Onde\s*:|Mensagem\s*:|Ultron\s*:)", ln, re.I) else ln
                         for ln in reply.strip().splitlines())
        e = Example(f"aprovado em {now:%d/%m/%Y %H:%M}", where if where in PLACES else "qualquer", msg, safe)
        with self.path.open("a", encoding="utf-8") as f:
            f.write("\n" + fmt(e))
        return e
