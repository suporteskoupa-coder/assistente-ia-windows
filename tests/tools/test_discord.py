import json

import httpx

from tests.tools.helpers import make_cfg
from ultron.tools.discord import discord_send


def client(status=200, seen=None):
    def handler(req: httpx.Request):
        if seen is not None:
            seen.append(req)
        return httpx.Response(status, json={"id": "1"})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_sends_with_bot_auth(tmp_path):
    seen = []
    msg = await discord_send(make_cfg(tmp_path), "geral", "oi", client(seen=seen))
    req = seen[0]
    assert str(req.url) == "https://discord.com/api/v10/channels/111/messages"
    assert req.headers["Authorization"] == "Bot tok"
    assert json.loads(req.content) == {"content": "oi"}
    assert "geral" in msg


async def test_http_error_reports_status(tmp_path):
    msg = await discord_send(make_cfg(tmp_path), "geral", "oi", client(status=403))
    assert msg.startswith("ERRO") and "403" in msg


async def test_unknown_alias_lists_channels(tmp_path):
    seen = []
    msg = await discord_send(make_cfg(tmp_path), "random", "oi", client(seen=seen))
    assert seen == [] and "geral" in msg and msg.startswith("ERRO")


async def test_missing_token(tmp_path):
    msg = await discord_send(make_cfg(tmp_path, discord_token=None), "geral", "oi", client())
    assert "ULTRON_DISCORD_TOKEN" in msg


async def test_too_long(tmp_path):
    msg = await discord_send(make_cfg(tmp_path), "geral", "x" * 2001, client())
    assert msg.startswith("ERRO") and "2000" in msg
