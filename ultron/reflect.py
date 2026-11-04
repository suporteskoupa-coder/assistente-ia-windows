"""Reflexão diária: o Claude relê o diário e reorganiza as conclusões sobre o usuário."""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta

from ultron.brains.base import Brain
from ultron.memory import CONCL_RE, Conclusion, Vault, _fold, parse_sources, source_id

REFLECT_PROMPT = """Você é a memória do Ultron. Abaixo estão o diário dos últimos 7 dias e as conclusões atuais sobre o usuário.
Reorganize as conclusões:
- junte as repetidas;
- suba a confiança das que o diário confirma (e some em "visto em");
- remova as que o diário contraria;
- adicione novas só se houver padrão claro (2 ou mais ocorrências);
- mantenha as fontes de cada uma (ao juntar, una as fontes).
Hoje é {today}. Use a data de hoje nas que você alterar.
Responda com a lista final entre <conclusoes> e </conclusoes>, uma por linha, exatamente neste formato:
- <texto> · confiança: baixa|média|alta · visto em N chats · AAAA-MM-DD · fontes: #id título; #id título

# Diário
{diary}

# Conclusões atuais
{current}
"""

TAG_RE = re.compile(r"<conclusoes>(.*?)</conclusoes>", re.S)


def apply_reflection(current: list[Conclusion], reply: str, today: date) -> list[Conclusion]:
    m = TAG_RE.search(reply)
    if not m:
        return current
    out = []
    for line in m.group(1).splitlines():
        mm = CONCL_RE.match(line.strip())
        if mm:
            out.append(Conclusion(mm["text"], mm["conf"], int(mm["seen"]), mm["date"], parse_sources(mm["src"])))
    # O modelo pode esquecer de copiar as fontes: recupera das conclusões atuais com o mesmo texto.
    old = {_fold(c.text): c.sources for c in current}
    for c in out:
        merged = list(c.sources)
        ids = {source_id(s) for s in merged}
        for s in old.get(_fold(c.text), []):
            if source_id(s) not in ids:
                merged.append(s)
                ids.add(source_id(s))
        c.sources = merged
        if merged:
            c.seen = len(ids)
    limit = (today - timedelta(days=30)).isoformat()
    return [c for c in out if not (c.seen <= 1 and c.date < limit)]


def _diary(vault: Vault, today: date, days: int = 7) -> str:
    parts = []
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        p = vault.root / "Ultron" / "Diario" / f"{d:%Y-%m-%d}.md"
        if p.exists():
            parts.append(p.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts) or "(vazio)"


async def reflect(vault: Vault, brain: Brain, today: date) -> int:
    current = vault.conclusions()
    prompt = REFLECT_PROMPT.format(
        today=today.isoformat(), diary=_diary(vault, today),
        current="\n".join(c.line() for c in current) or "(nenhuma)",
    )
    texts = []
    async for ev in brain.send(None, [], prompt, "Responda só o pedido."):
        if ev.kind == "text":
            texts.append(ev.text)
        elif ev.kind == "error":
            return len(current)
    new = apply_reflection(current, "\n".join(texts), today)
    if new != current:
        vault.save_conclusions(new)
    return len(new)


def seconds_until(now: datetime, hour: int) -> float:
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def scheduler(vault: Vault, brain: Brain, hour: int = 4) -> None:
    while True:
        await asyncio.sleep(seconds_until(datetime.now(), hour))
        try:
            await reflect(vault, brain, date.today())
        except Exception:
            pass  # a reflexão nunca derruba o Ultron; tenta de novo amanhã
