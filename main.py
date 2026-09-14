import asyncio
import logging
import os

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from pytz import timezone

from app.config import settings
from app.bot.commands import setup_commands
from app.scheduler.reminders import send_due_reminders, maintain_raids
from app.database.session import SessionLocal
from app.repositories.raids import list_raids_for_view_restore
from app.repositories.classes import list_classes
from app.bot.ui import build_signup_view
from app.bot.ephemeral import install_ephemeral_autodelete_patch


def setup_logging() -> None:
    os.makedirs(os.path.dirname(settings.log_file) or ".", exist_ok=True)

    root_level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(
        level=root_level,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    error_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s"))
    logging.getLogger().addHandler(error_handler)

    if not settings.debug:
        logging.getLogger("apscheduler").setLevel(logging.WARNING)
        logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
        logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
        logging.getLogger("discord.client").setLevel(logging.WARNING)
        logging.getLogger("discord.gateway").setLevel(logging.WARNING)


install_ephemeral_autodelete_patch()
setup_logging()
log = logging.getLogger("SP4RK")


class SparkBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)
        self.scheduler = AsyncIOScheduler(timezone=timezone(settings.timezone))

    async def setup_hook(self):
        await setup_commands(self)
        if settings.sync_commands:
            synced = await self.tree.sync()
            log.info("Synced %s global slash commands", len(synced))
        self.scheduler.add_job(send_due_reminders, IntervalTrigger(seconds=1), args=[self], id="send_due_reminders", replace_existing=True)
        self.scheduler.add_job(maintain_raids, IntervalTrigger(seconds=30), args=[self], id="maintain_raids", replace_existing=True)
        self.scheduler.start()

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.CustomActivity(name=settings.bot_status)
        )
        try:
            async with SessionLocal() as session:
                for guild in self.guilds:
                    raids = await list_raids_for_view_restore(session, guild.id)
                    classes = await list_classes(session, guild.id)
                    for raid in raids:
                        self.add_view(build_signup_view(raid.id, classes))
            log.info("Persistent signup views restored")
        except Exception as exc:
            log.warning("Could not restore views: %s", exc)


async def main():
    if not settings.discord_token or settings.discord_token == "PASTE_NEW_TOKEN_HERE":
        raise RuntimeError("Заполни DISCORD_TOKEN в .env")
    bot = SparkBot()
    await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
