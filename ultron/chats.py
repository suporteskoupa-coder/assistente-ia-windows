"""Chats e mensagens guardados em SQLite."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  brain TEXT NOT NULL,
  claude_session_id TEXT,
  continues_from INTEGER,
  created TEXT NOT NULL,
  updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL REFERENCES chats(id),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created TEXT NOT NULL
);
"""


@dataclass
class Chat:
    id: int
    title: str
    brain: str
    claude_session_id: str | None
    continues_from: int | None
    created: str
    updated: str


@dataclass
class Message:
    id: int
    chat_id: int
    role: str
    content: str
    created: str


def _now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


class ChatStore:
    def __init__(self, db_path: Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def create(self, brain: str, title: str = "Novo chat", continues_from: int | None = None) -> Chat:
        now = _now()
        cur = self._db.execute(
            "INSERT INTO chats (title, brain, continues_from, created, updated) VALUES (?,?,?,?,?)",
            (title, brain, continues_from, now, now),
        )
        self._db.commit()
        return self.get(cur.lastrowid)

    def get(self, chat_id: int) -> Chat:
        row = self._db.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if row is None:
            raise KeyError(chat_id)
        return Chat(**dict(row))

    def list(self) -> list[Chat]:
        rows = self._db.execute("SELECT * FROM chats ORDER BY updated DESC, id DESC").fetchall()
        return [Chat(**dict(r)) for r in rows]

    def add_message(self, chat_id: int, role: str, content: str) -> Message:
        self.get(chat_id)
        now = _now()
        cur = self._db.execute(
            "INSERT INTO messages (chat_id, role, content, created) VALUES (?,?,?,?)",
            (chat_id, role, content, now),
        )
        self._db.execute("UPDATE chats SET updated=? WHERE id=?", (now, chat_id))
        self._db.commit()
        return Message(cur.lastrowid, chat_id, role, content, now)

    def messages(self, chat_id: int) -> list[Message]:
        rows = self._db.execute(
            "SELECT * FROM messages WHERE chat_id=? ORDER BY id", (chat_id,)
        ).fetchall()
        return [Message(**dict(r)) for r in rows]

    def set_session(self, chat_id: int, session_id: str) -> None:
        self._db.execute("UPDATE chats SET claude_session_id=? WHERE id=?", (session_id, chat_id))
        self._db.commit()

    def rename(self, chat_id: int, title: str) -> None:
        self._db.execute("UPDATE chats SET title=? WHERE id=?", (title, chat_id))
        self._db.commit()
