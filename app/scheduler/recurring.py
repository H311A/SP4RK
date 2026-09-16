import logging
from datetime import datetime, timedelta

import discord

from app.database.models import Reminder
from app.database.session import SessionLocal
from app.repositories import raids as raids_repo
from app.repositories.classes import list_classes
from app.repositories.templates import list_recurring_templates, mark_recurrence_run
from app.services import events_calendar
from app.services.raids import build_message_payload

log = logging.getLogger("SP4RK.recurring")


def _next_occurrence(template, now: datetime) -> datetime:
    try:
        hour, minute = (int(part) for part in (template.recurrence_time or "19:00").split(":"))
    except ValueError:
        hour, minute = 19, 0
    target_day = template.recurrence_day_of_week if template.recurrence_day_of_week is not None else 0
    days_ahead = (target_day - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


async def publish_due_recurring_events(bot: discord.Client) -> None:
    async with SessionLocal() as session:
        templates = await list_recurring_templates(session)
        now = datetime.utcnow()

        for template in templates:
            next_run = _next_occurrence(template, now)
            lead = timedelta(days=template.recurrence_lead_days)
            if next_run - now > lead:
                continue
            if template.last_recurrence_run and template.last_recurrence_run >= next_run - timedelta(days=6):
                continue

            guild = bot.get_guild(template.guild_id)
            channel = guild.get_channel(template.channel_id) if guild else None
            if channel is None:
                log.warning("Recurring template %s: channel not found, skipping this cycle", template.id)
                continue

            raid = await raids_repo.create_raid(
                session,
                guild_id=template.guild_id,
                game_id=template.game_id,
                template_id=template.id,
                title=template.title,
                description=template.description,
                starts_at=next_run,
                duration_minutes=template.duration_minutes,
                channel_id=template.channel_id,
                created_by=template.created_by,
                reminder_minutes=template.reminder_minutes,
                mention_role_id=template.mention_role_id,
                participant_limit=template.participant_limit,
                banner_path=template.banner_path,
            )
            session.add(Reminder(raid_id=raid.id, minutes_before=template.reminder_minutes))
            await mark_recurrence_run(session, template, next_run)
            await session.flush()

            classes = await list_classes(session, template.game_id, active_only=False)

            from app.bot.views.signup import build_signup_view

            _main_embed, embeds, files = build_message_payload(raid, classes)
            view = build_signup_view(raid.id, classes, disabled=False)
            content = f"<@&{template.mention_role_id}>" if template.mention_role_id else None

            message = await channel.send(content=content, embeds=embeds, files=files, view=view)
            raid.message_id = message.id
            raid.discord_event_id = await events_calendar.sync_scheduled_event(guild, raid)

            await session.commit()
            log.info("Auto-published recurring raid %s from template %s", raid.id, template.id)
