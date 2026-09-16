"""
Одноразовый скрипт: убирает старую ГЛОБАЛЬНУЮ регистрацию команд бота
(например, дублирующийся /spark, который остался с тех пор, когда
SYNC_GUILD_ID ещё не был задан).

Запускать один раз, потом просто обычным образом стартовать бота:

    python scripts/clear_global_commands.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord
from discord import app_commands

from app.config import settings


async def main() -> None:
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @client.event
    async def on_ready() -> None:
        tree.clear_commands(guild=None)
        synced = await tree.sync()
        print(f"Глобальные команды очищены. Осталось глобальных команд: {len(synced)}.")
        await client.close()

    await client.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
