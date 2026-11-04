"""Conexão do bot com o Discord.

- DMs do dono → controle pelo celular (on_dm).
- Mensagens em canais do servidor → respostas por você (on_guild), só se ativado.
"""
from __future__ import annotations

from typing import Awaitable, Callable

OnDm = Callable[[int, str], Awaitable[None]]
OnGuild = Callable[[str, str, bool, str, int], Awaitable[str | None]]


def make_client(owner_id: int | None, on_dm: OnDm | None = None, on_guild: OnGuild | None = None):
    import discord

    intents = discord.Intents.none()
    intents.dm_messages = True  # o conteúdo de DMs chega sem a permissão privilegiada
    if on_guild is not None:
        # ler mensagens do servidor exige "Message Content Intent" ligado no portal do Discord
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True

    class UltronBot(discord.Client):
        async def on_message(self, message):
            if message.author == self.user:
                return
            if isinstance(message.channel, discord.DMChannel):
                if on_dm is not None and not message.author.bot:
                    await on_dm(message.author.id, message.content)
                return
            if on_guild is not None and message.guild is not None:
                reply = await on_guild(str(message.channel.id), message.author.display_name,
                                       message.author.bot, message.content, message.author.id)
                if reply:
                    await message.reply(reply, mention_author=False)

    client = UltronBot(intents=intents)

    async def send_to_owner(text: str) -> None:
        if owner_id is None:
            return
        user = client.get_user(owner_id) or await client.fetch_user(owner_id)
        await user.send(text)

    return client, send_to_owner
