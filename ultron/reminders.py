"""Lembretes: guardados no ultron.db, disparados pelo núcleo com notificação do Windows e cartão na HUD."""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from ultron.memory import Vault

REPEATS = {"diario": timedelta(days=1), "semanal": timedelta(weeks=1)}
WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
LATE_WINDOW = timedelta(hours=24)
FMT = "%Y-%m-%dT%H:%M"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  due TEXT NOT NULL,
  repeat TEXT,
  status TEXT NOT NULL,
  created TEXT NOT NULL,
  fired_at TEXT
);
"""


@dataclass
class Reminder:
    id: int
    text: str
    due: str
    repeat: str | None
    status: str  # pendente | disparado | cancelado | perdido
    created: str
    fired_at: str | None

    @property
    def due_dt(self) -> datetime:
        return datetime.strptime(self.due, FMT)


def describe_when(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]}, {dt:%d/%m} às {dt:%H:%M}"


def parse_when(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text.strip()).replace(second=0, microsecond=0, tzinfo=None)
    except ValueError:
        raise ValueError(f"Data inválida: '{text}'. Use o formato AAAA-MM-DD HH:MM.")


class ReminderStore:
    """Compartilhado entre o núcleo e o servidor de ferramentas (processos diferentes): SQLite resolve."""

    def __init__(self, db_path: Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def _get(self, rid: int) -> Reminder | None:
        row = self._db.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
        return Reminder(**dict(row)) if row else None

    def _rows(self, where: str, args=()) -> list[Reminder]:
        return [Reminder(**dict(r)) for r in self._db.execute(f"SELECT * FROM reminders WHERE {where} ORDER BY due, id", args)]

    def _set_due(self, rid: int, due: datetime) -> None:
        self._db.execute("UPDATE reminders SET due=? WHERE id=?", (due.strftime(FMT), rid))
        self._db.commit()

    def create(self, text: str, due: datetime, repeat: str | None = None, now: datetime | None = None) -> Reminder:
        now = now or datetime.now()
        if repeat and repeat not in REPEATS:
            raise ValueError(f"Repetição inválida: {repeat}. Use: {', '.join(REPEATS)}.")
        if due <= now:
            raise ValueError(f"Esse horário ({describe_when(due)}) já passou.")
        if not text.strip():
            raise ValueError("O lembrete precisa de um texto.")
        cur = self._db.execute(
            "INSERT INTO reminders (text, due, repeat, status, created) VALUES (?,?,?,?,?)",
            (text.strip(), due.strftime(FMT), repeat, "pendente", now.isoformat(timespec="minutes")),
        )
        self._db.commit()
        return self._get(cur.lastrowid)

    def list_pending(self) -> list[Reminder]:
        return self._rows("status='pendente'")

    def cancel(self, rid: int) -> bool:
        cur = self._db.execute("UPDATE reminders SET status='cancelado' WHERE id=? AND status='pendente'", (rid,))
        self._db.commit()
        return cur.rowcount > 0

    def due(self, now: datetime) -> list[Reminder]:
        return self._rows("status='pendente' AND due<=?", (now.strftime(FMT),))

    def mark_fired(self, r: Reminder, now: datetime) -> Reminder:
        if r.repeat:
            nxt = r.due_dt
            while nxt <= now:
                nxt += REPEATS[r.repeat]
            self._db.execute("UPDATE reminders SET due=?, fired_at=? WHERE id=?",
                             (nxt.strftime(FMT), now.isoformat(timespec="minutes"), r.id))
        else:
            self._db.execute("UPDATE reminders SET status='disparado', fired_at=? WHERE id=?",
                             (now.isoformat(timespec="minutes"), r.id))
        self._db.commit()
        return self._get(r.id)

    def mark_lost(self, r: Reminder) -> None:
        if r.repeat:
            return
        self._db.execute("UPDATE reminders SET status='perdido' WHERE id=?", (r.id,))
        self._db.commit()

    def snooze(self, rid: int, minutes: int, now: datetime) -> Reminder | None:
        r = self._get(rid)
        if r is None:
            return None
        due = (now + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
        if r.repeat:
            # repetição continua no horário normal; o adiamento vira um lembrete avulso
            return self.create(r.text, due, None, now)
        self._db.execute("UPDATE reminders SET due=?, status='pendente' WHERE id=?", (due.strftime(FMT), rid))
        self._db.commit()
        return self._get(rid)


def windows_notify(title: str, text: str) -> None:
    """Notificação do Windows (não rouba o foco do jogo). Fora do Windows não faz nada."""
    if sys.platform != "win32":
        return
    from windows_toasts import Toast, WindowsToaster

    WindowsToaster("Ultron").show_toast(Toast(text_fields=[title, text]))


class ReminderScheduler:
    def __init__(self, store: ReminderStore, vault: Vault, notify: Callable[[str, str], None] = windows_notify,
                 publish: Callable[[dict], None] = lambda m: None, now: Callable[[], datetime] = datetime.now):
        self.store = store
        self.vault = vault
        self.notify = notify
        self.publish = publish
        self.now = now
        self._active: dict[int, dict] = {}
        self.missed: list[Reminder] = []

    def _fire(self, r: Reminder, late: bool) -> None:
        now = self.now()
        self.store.mark_fired(r, now)
        msg = {"type": "reminder", "id": r.id, "text": r.text, "due": r.due, "late": late}
        self._active[r.id] = msg
        self.vault.log(f"lembrete: {r.text}{' (atrasado)' if late else ''}", now)
        try:
            self.notify("Ultron · lembrete" + (" atrasado" if late else ""), r.text)
        except Exception as e:  # a HUD ainda mostra o cartão
            self.vault.log(f"falha na notificação do Windows: {e}", now)
        self.publish(msg)

    async def startup(self) -> None:
        now = self.now()
        for r in self.store.due(now):
            if now - r.due_dt <= LATE_WINDOW:
                self._fire(r, late=True)
            else:
                self.missed.append(r)
                if r.repeat:
                    self.store.mark_fired(r, now)
                else:
                    self.store.mark_lost(r)

    async def tick(self) -> None:
        for r in self.store.due(self.now()):
            self._fire(r, late=False)

    async def run(self, interval: float = 15) -> None:
        await self.startup()
        while True:
            await asyncio.sleep(interval)
            try:
                await self.tick()
            except Exception:
                pass  # nunca derruba o núcleo

    def active(self) -> list[dict]:
        return list(self._active.values())

    def ack(self, rid: int) -> None:
        self._active.pop(rid, None)

    def snooze(self, rid: int, minutes: int = 10) -> None:
        self._active.pop(rid, None)
        self.store.snooze(rid, minutes, self.now())

    def briefing(self, vault: Vault) -> dict:
        now = self.now()
        today = [r for r in self.store.list_pending() if r.due_dt.date() == now.date()]
        since = (now.date() - timedelta(days=1)).isoformat()
        return {
            "reminders_today": [{"id": r.id, "text": r.text, "when": f"{r.due_dt:%H:%M}"} for r in today],
            "pending_count": len(vault.pending()),
            "new_conclusions": [asdict(c) for c in vault.conclusions() if c.date >= since],
            "missed": [{"id": r.id, "text": r.text, "when": describe_when(r.due_dt)} for r in self.missed],
        }
