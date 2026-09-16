import logging

import discord
import pytz

log = logging.getLogger("SP4RK.events_calendar")


def _aware(dt):
    return pytz.utc.localize(dt)


async def sync_scheduled_event(guild: discord.Guild, raid) -> int | None:
    channel = guild.get_channel(raid.channel_id)
    location = f"#{channel.name}" if channel else "Discord"

    try:
        if raid.discord_event_id:
            try:
                event = await guild.fetch_scheduled_event(raid.discord_event_id)
                await event.edit(
                    name=raid.title[:100],
                    start_time=_aware(raid.starts_at),
                    end_time=_aware(raid.ends_at),
                    description=(raid.description or "")[:1000],
                )
                return event.id
            except discord.NotFound:
                pass

        event = await guild.create_scheduled_event(
            name=raid.title[:100],
            start_time=_aware(raid.starts_at),
            end_time=_aware(raid.ends_at),
            entity_type=discord.EntityType.external,
            location=location[:100],
            description=(raid.description or "")[:1000],
            privacy_level=discord.PrivacyLevel.guild_only,
        )
        return event.id
    except discord.Forbidden:
        log.warning("No permission to manage scheduled events in guild %s", guild.id)
        return None
    except Exception as exc:
        log.warning("Could not sync scheduled event for raid %s: %s", raid.id, exc)
        return None


async def delete_scheduled_event(guild: discord.Guild, discord_event_id: int | None) -> None:
    if not discord_event_id:
        return
    try:
        event = await guild.fetch_scheduled_event(discord_event_id)
        await event.delete()
    except (discord.NotFound, discord.Forbidden):
        pass
    except Exception as exc:
        log.warning("Could not delete scheduled event %s: %s", discord_event_id, exc)
