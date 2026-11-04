"""Interface comum dos cérebros."""
from __future__ import annotations

from typing import AsyncIterator, Protocol

from ultron.chats import Message
from ultron.events import Event


class Brain(Protocol):
    name: str

    def send(self, session_id: str | None, history: list[Message], text: str, system: str,
             chat_ref: str | None = None) -> AsyncIterator[Event]:
        ...
