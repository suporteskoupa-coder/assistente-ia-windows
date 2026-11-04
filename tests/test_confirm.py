import asyncio

from ultron.confirm import ConfirmBroker


async def _first_pending(broker):
    for _ in range(100):
        if broker.pending():
            return broker.pending()[0]
        await asyncio.sleep(0.001)
    raise AssertionError("nenhum pedido")


async def test_answer_allow_returns_true():
    b = ConfirmBroker(timeout=2)
    task = asyncio.create_task(b.request("discord_enviar", {"texto": "oi"}))
    p = await _first_pending(b)
    assert p["action"] == "discord_enviar" and p["detail"] == {"texto": "oi"}
    b.answer(p["id"], True)
    assert await task is True
    assert b.pending() == []


async def test_answer_deny_returns_false():
    b = ConfirmBroker(timeout=2)
    task = asyncio.create_task(b.request("x", {}))
    b.answer((await _first_pending(b))["id"], False)
    assert await task is False


async def test_timeout_denies_and_clears():
    b = ConfirmBroker(timeout=0.05)
    assert await b.request("x", {}) is False
    assert b.pending() == []


def test_answer_unknown_id_is_noop():
    ConfirmBroker().answer("nope", True)


async def test_subscriber_receives_request():
    b = ConfirmBroker(timeout=0.05)
    q = b.subscribe()
    await b.request("organizar_pasta", {"plano": "ab"})
    item = q.get_nowait()
    assert item["action"] == "organizar_pasta"


async def test_edited_input_returned():
    b = ConfirmBroker(timeout=2)
    task = asyncio.create_task(b.request("discord_enviar", {"texto": "oi"}))
    rid = (await _first_pending(b))["id"]
    b.answer(rid, True, edited={"texto": "olá"})
    assert await task is True
    assert b.edited_input(rid) == {"texto": "olá"}


async def test_unsubscribe():
    b = ConfirmBroker(timeout=0.05)
    q = b.subscribe()
    b.unsubscribe(q)
    await b.request("x", {})
    assert q.empty()
