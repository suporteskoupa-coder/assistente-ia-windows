"""Pedidos de confirmação que a HUD responde. Sem resposta no prazo = negado."""
from __future__ import annotations

import asyncio
import uuid


class ConfirmBroker:
    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout
        self._pending: dict[str, dict] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._edited: dict[str, dict | None] = {}
        self._subs: list[asyncio.Queue] = []

    async def request(self, action: str, detail: dict) -> bool:
        allow, _ = await self.request_detail(action, detail)
        return allow

    async def request_detail(self, action: str, detail: dict, meta: dict | None = None) -> tuple[bool, dict | None]:
        rid = uuid.uuid4().hex[:12]
        item = {"id": rid, "action": action, "detail": detail, **(meta or {})}
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = item
        self._futures[rid] = fut
        for q in list(self._subs):
            q.put_nowait(item)
        try:
            allow = await asyncio.wait_for(fut, self.timeout)
        except asyncio.TimeoutError:
            allow = False
        finally:
            self._pending.pop(rid, None)
            self._futures.pop(rid, None)
        return bool(allow), self._edited.get(rid)

    def answer(self, request_id: str, allow: bool, edited: dict | None = None) -> None:
        fut = self._futures.get(request_id)
        if fut is None or fut.done():
            return
        self._edited[request_id] = edited
        fut.get_loop().call_soon_threadsafe(_resolve, fut, allow)

    def pending(self) -> list[dict]:
        return list(self._pending.values())

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.append(q)
        return q

    def broadcast(self, msg: dict) -> None:
        """Envia uma mensagem qualquer (com "type") para todas as HUDs conectadas."""
        for q in list(self._subs):
            q.put_nowait(msg)

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def edited_input(self, request_id: str) -> dict | None:
        return self._edited.get(request_id)


def _resolve(fut: asyncio.Future, value: bool) -> None:
    if not fut.done():
        fut.set_result(value)
