import logging

import discord

from app.database.session import SessionLocal
from app.repositories.raids import (
    archive_raid,
    delete_raid,
    due_raids_to_archive,
    due_reminders,
    mark_reminder_sent,
    old_raids_to_purge,
)
from app.services.raids import refresh_raid_message
from app.utils.time import discord_ts

log = logging.getLogger("SP4RK.reminders")
REMINDER_STATUSES = {"accepted", "backup", "maybe"}


async def _raid_message_exists(bot: discord.Client, raid) -> bool:
    # У события может ещё не быть message_id в первые секунды после создания:
    # карточка уже отправляется, но ID сообщения ещё не успел сохраниться в БД.
    # Такое событие нельзя удалять как "потерянное".
    if not raid.message_id:
        return True
    try:
        channel = bot.get_channel(raid.channel_id) or await bot.fetch_channel(raid.channel_id)
        await channel.fetch_message(raid.message_id)
        return True
    except (discord.NotFound, discord.Forbidden):
        return False
    except Exception as exc:
        log.warning("Could not check raid message %s: %s", raid.id, exc)
        return True


async def _delete_raid_message(bot: discord.Client, raid) -> bool:
    if not raid.message_id:
        return False
    try:
        channel = bot.get_channel(raid.channel_id) or await bot.fetch_channel(raid.channel_id)
        message = await channel.fetch_message(raid.message_id)
        await message.delete()
        return True
    except discord.NotFound:
        return False
    except discord.Forbidden:
        log.warning("No permissions to delete old raid message: %s", raid.id)
        return False
    except Exception as exc:
        log.warning("Could not delete old raid message %s: %s", raid.id, exc)
        return False


async def send_due_reminders(bot: discord.Client) -> None:
    async with SessionLocal() as session:
        reminders = await due_reminders(session)

        for reminder in reminders:
            raid = reminder.raid

            if not await _raid_message_exists(bot, raid):
                log.warning("Raid message missing; deleting raid from database: %s", raid.id)
                await delete_raid(session, raid)
                await session.commit()
                continue

            sent_count = 0
            failed_count = 0

            for signup in raid.signups:
                if signup.status not in REMINDER_STATUSES:
                    continue
                if not getattr(signup, "notifications_enabled", True):
                    continue

                try:
                    user = await bot.fetch_user(signup.user_id)
                    cls = signup.raid_class

                    if signup.status == "accepted":
                        status_text = "Основной состав"
                    elif signup.status == "backup":
                        status_text = "Запас"
                    else:
                        status_text = "Возможно будете"

                    await user.send(
                        "\n".join([
                            "**Напоминание о событии**",
                            "",
                            f"**{raid.title}**",
                            f"🕒 Начало: {discord_ts(raid.starts_at, 'F')}.",
                            f"⏳ Начнётся: {discord_ts(raid.starts_at, 'R')}.",
                            f"Статус: **{status_text}**.",
                            f"Класс: {cls.icon + ' ' + cls.name if cls else 'не выбран'}.",
                            "",
                            "Участники события ждут тебя.",
                        ])
                    )
                    sent_count += 1
                except discord.Forbidden:
                    failed_count += 1
                    log.warning("DM closed for user %s", signup.user_id)
                except Exception as exc:
                    failed_count += 1
                    log.warning("Could not send reminder to %s: %s", signup.user_id, exc)

            if sent_count or failed_count:
                log.info("Reminder for raid %s sent: %s, failed: %s", raid.id, sent_count, failed_count)
            await mark_reminder_sent(session, reminder)

        await session.commit()


async def maintain_raids(bot: discord.Client) -> None:
    async with SessionLocal() as session:
        raids = await due_raids_to_archive(session)
        for raid in raids:
            if not await _raid_message_exists(bot, raid):
                log.warning("Raid message missing during maintenance; deleting raid: %s", raid.id)
                await delete_raid(session, raid)
            else:
                await archive_raid(session, raid)
        await session.commit()

    for raid in raids:
        try:
            await refresh_raid_message(bot, raid.id)
            log.info("Raid archived and message refreshed: %s", raid.id)
        except discord.NotFound:
            async with SessionLocal() as session:
                db_raid = await session.get(type(raid), raid.id)
                if db_raid:
                    await delete_raid(session, db_raid)
                    await session.commit()
            log.warning("Raid message not found while archiving; raid deleted: %s", raid.id)
        except discord.Forbidden:
            log.warning("No permissions to refresh archived raid message: %s", raid.id)
        except Exception as exc:
            log.warning("Could not refresh archived raid message %s: %s", raid.id, exc)

    async with SessionLocal() as session:
        old_raids = await old_raids_to_purge(session)
        deleted = 0
        for raid in old_raids:
            await _delete_raid_message(bot, raid)
            await delete_raid(session, raid)
            deleted += 1
        await session.commit()
        if deleted:
            log.info("Deleted %s old raid card(s) and purged raid(s) from database", deleted)
