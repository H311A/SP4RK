import logging
import os

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from discord.ext import commands
from pytz import timezone

from app.bot import formatting as fmt
from app.bot.spark_command import setup_commands
from app.bot.views.signup import build_signup_view
from app.config import settings
from app.database.session import SessionLocal
from app.repositories.classes import list_classes
from app.repositories.raids import delete_raid, get_raid_by_message_id, list_raids_for_view_restore
from app.scheduler.recurring import publish_due_recurring_events
from app.scheduler.reminders import maintain_raids, send_due_reminders

log = logging.getLogger("SP4RK")


def setup_logging() -> None:
    os.makedirs(os.path.dirname(settings.log_file) or ".", exist_ok=True)

    root_level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(level=root_level, format="%(levelname)s:%(name)s:%(message)s")

    error_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s"))
    logging.getLogger().addHandler(error_handler)

    if not settings.debug:
        for name in (
            "apscheduler",
            "apscheduler.executors.default",
            "apscheduler.scheduler",
            "discord.client",
            "discord.gateway",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)


class SparkBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.scheduler = AsyncIOScheduler(timezone=timezone(settings.timezone))

    async def setup_hook(self) -> None:
        setup_commands(self)
        if settings.sync_commands:
            if settings.sync_guild_id:
                guild_obj = discord.Object(id=settings.sync_guild_id)
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                log.info("Synced %s command(s) to test guild %s (instant)", len(synced), settings.sync_guild_id)
            else:
                synced = await self.tree.sync()
                log.info("Synced %s command(s) globally", len(synced))

        self.scheduler.add_job(
            send_due_reminders, IntervalTrigger(seconds=15), args=[self], id="send_due_reminders", replace_existing=True
        )
        self.scheduler.add_job(
            maintain_raids, IntervalTrigger(seconds=30), args=[self], id="maintain_raids", replace_existing=True
        )
        self.scheduler.add_job(
            publish_due_recurring_events,
            IntervalTrigger(minutes=30),
            args=[self],
            id="publish_recurring",
            replace_existing=True,
        )
        self.scheduler.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        try:
            await self.change_presence(activity=discord.CustomActivity(name=settings.bot_status))
        except Exception as exc:
            log.warning("Could not set presence: %s", exc)

        try:
            async with SessionLocal() as session:
                for guild in self.guilds:
                    raids = await list_raids_for_view_restore(session, guild.id)
                    for raid in raids:
                        classes = await list_classes(session, raid.game_id)
                        self.add_view(build_signup_view(raid.id, classes, disabled=not fmt.is_open_now(raid)))
            log.info("Persistent signup views restored")
        except Exception as exc:
            log.warning("Could not restore views: %s", exc)

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        try:
            async with SessionLocal() as session:
                raid = await get_raid_by_message_id(session, payload.message_id)
                if raid is None:
                    return
                await delete_raid(session, raid)
                await session.commit()
            log.info("Raid %s removed from DB after its message was deleted", raid.id)
        except Exception as exc:
            log.warning("Could not clean up raid after message delete: %s", exc)
