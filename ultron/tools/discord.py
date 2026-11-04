"""Enviar mensagem num canal do Discord pelo bot oficial (API REST)."""
from __future__ import annotations

import httpx

from ultron.config import Config

API = "https://discord.com/api/v10"


async def discord_send(cfg: Config, channel_alias: str, text: str, client: httpx.AsyncClient) -> str:
    if not cfg.discord_token:
        return "ERRO: bot do Discord sem token. Defina a variável de ambiente ULTRON_DISCORD_TOKEN."
    channel_id = cfg.discord_channels.get(channel_alias.lstrip("#"))
    if channel_id is None:
        known = ", ".join(sorted(cfg.discord_channels)) or "nenhum"
        return f"ERRO: canal '{channel_alias}' não configurado. Canais: {known}."
    if not text.strip():
        return "ERRO: mensagem vazia."
    if len(text) > 2000:
        return "ERRO: o Discord aceita no máximo 2000 caracteres por mensagem."
    try:
        r = await client.post(
            f"{API}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {cfg.discord_token}"},
            json={"content": text},
            timeout=15,
        )
    except httpx.HTTPError as e:
        return f"ERRO: falha de conexão com o Discord: {e}"
    if r.status_code >= 300:
        hint = " Verifique se o bot está no servidor e tem permissão Send Messages." if r.status_code in (401, 403) else ""
        return f"ERRO: Discord respondeu {r.status_code}.{hint}"
    return f"Mensagem enviada em #{channel_alias.lstrip('#')}."
