import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Raid, RaidSignup, Reminder

REGISTRATION_CLOSE_BEFORE = timedelta(minutes=1)
PURGE_AFTER = timedelta(hours=1)


def utcnow() -> datetime:
    return datetime.utcnow()


def is_registration_open(raid: Raid) -> bool:
    return (
        not raid.cancelled
        and not raid.archived
        and utcnow() < raid.starts_at - REGISTRATION_CLOSE_BEFORE
    )


def is_registration_closed(raid: Raid) -> bool:
    return not is_registration_open(raid)


async def create_raid(
    session: AsyncSession,
    guild_id: int,
    title: str,
    description: str | None,
    starts_at: datetime,
    channel_id: int,
    created_by: int,
    reminder_minutes: int,
    mention_role_id: int | None,
    participant_limit: int = 0,
) -> Raid:
    raid = Raid(
        guild_id=guild_id,
        title=title,
        description=description,
        starts_at=starts_at,
        channel_id=channel_id,
        created_by=created_by,
        reminder_minutes=reminder_minutes,
        mention_role_id=mention_role_id,
        participant_limit=participant_limit,
    )
    session.add(raid)
    await session.flush()
    if reminder_minutes > 0:
        session.add(Reminder(raid_id=raid.id, minutes_before=reminder_minutes, sent=False))
    await session.flush()
    return raid


async def get_raid(session: AsyncSession, raid_id: uuid.UUID) -> Raid | None:
    result = await session.execute(
        select(Raid)
        .where(Raid.id == raid_id)
        .options(
            selectinload(Raid.signups).selectinload(RaidSignup.raid_class),
            selectinload(Raid.reminders),
        )
    )
    return result.scalar_one_or_none()


async def delete_raid(session: AsyncSession, raid: Raid) -> None:
    await session.delete(raid)
    await session.flush()


async def delete_raid_by_id(session: AsyncSession, raid_id: uuid.UUID) -> bool:
    result = await session.execute(delete(Raid).where(Raid.id == raid_id))
    await session.flush()
    return bool(result.rowcount)


async def list_active_raids(session: AsyncSession, guild_id: int) -> list[Raid]:
    now = utcnow()
    result = await session.execute(
        select(Raid)
        .where(
            Raid.guild_id == guild_id,
            Raid.cancelled.is_(False),
            Raid.archived.is_(False),
            Raid.starts_at > now,
        )
        .order_by(Raid.starts_at.asc())
        .options(selectinload(Raid.signups).selectinload(RaidSignup.raid_class))
    )
    return list(result.scalars().all())


async def list_raids_for_view_restore(session: AsyncSession, guild_id: int) -> list[Raid]:
    now = utcnow()
    result = await session.execute(
        select(Raid)
        .where(
            Raid.guild_id == guild_id,
            Raid.cancelled.is_(False),
            Raid.archived.is_(False),
            Raid.starts_at > now + REGISTRATION_CLOSE_BEFORE,
        )
        .order_by(Raid.starts_at.asc())
        .options(selectinload(Raid.signups).selectinload(RaidSignup.raid_class))
    )
    return list(result.scalars().all())


async def set_raid_message(session: AsyncSession, raid: Raid, message_id: int) -> None:
    raid.message_id = message_id
    await session.flush()


async def cancel_raid(session: AsyncSession, raid: Raid) -> None:
    raid.cancelled = True
    await session.flush()


async def archive_raid(session: AsyncSession, raid: Raid) -> None:
    raid.archived = True
    await session.flush()


async def due_raids_to_archive(session: AsyncSession) -> list[Raid]:
    now = utcnow()
    result = await session.execute(
        select(Raid)
        .where(
            Raid.cancelled.is_(False),
            Raid.archived.is_(False),
            Raid.starts_at <= now,
        )
        .options(selectinload(Raid.signups).selectinload(RaidSignup.raid_class))
    )
    return list(result.scalars().all())


async def old_raids_to_purge(session: AsyncSession) -> list[Raid]:
    cutoff = utcnow() - PURGE_AFTER
    result = await session.execute(
        select(Raid)
        .where(Raid.starts_at <= cutoff)
        .options(selectinload(Raid.signups).selectinload(RaidSignup.raid_class))
    )
    return list(result.scalars().all())


async def purge_old_raids(session: AsyncSession) -> int:
    cutoff = utcnow() - PURGE_AFTER
    result = await session.execute(delete(Raid).where(Raid.starts_at <= cutoff))
    await session.flush()
    return int(result.rowcount or 0)




def accepted_count_excluding_user(raid: Raid, user_id: int | None = None) -> int:
    return sum(
        1
        for signup in raid.signups
        if signup.status == "accepted" and (user_id is None or signup.user_id != user_id)
    )


def event_main_is_full(raid: Raid, user_id: int | None = None) -> bool:
    limit = getattr(raid, "participant_limit", 0) or 0
    if limit <= 0:
        return False
    return accepted_count_excluding_user(raid, user_id) >= limit

async def upsert_signup(
    session: AsyncSession,
    raid_id: uuid.UUID,
    user_id: int,
    display_name: str,
    class_id: uuid.UUID | None,
    status: str,
) -> RaidSignup:
    result = await session.execute(select(RaidSignup).where(RaidSignup.raid_id == raid_id, RaidSignup.user_id == user_id))
    signup = result.scalar_one_or_none()
    if signup:
        signup.class_id = class_id
        signup.status = status
        signup.display_name = display_name
        # При смене статуса не сбрасываем личную настройку уведомлений.
    else:
        signup = RaidSignup(
            raid_id=raid_id,
            user_id=user_id,
            display_name=display_name,
            class_id=class_id,
            status=status,
            notifications_enabled=True,
        )
        session.add(signup)
    await session.flush()
    return signup


async def toggle_notifications(session: AsyncSession, raid_id: uuid.UUID, user_id: int) -> RaidSignup | None:
    result = await session.execute(select(RaidSignup).where(RaidSignup.raid_id == raid_id, RaidSignup.user_id == user_id))
    signup = result.scalar_one_or_none()
    if not signup:
        return None
    signup.notifications_enabled = not signup.notifications_enabled
    await session.flush()
    return signup


async def delete_signup(session: AsyncSession, raid_id: uuid.UUID, user_id: int) -> bool:
    result = await session.execute(select(RaidSignup).where(RaidSignup.raid_id == raid_id, RaidSignup.user_id == user_id))
    signup = result.scalar_one_or_none()
    if not signup:
        return False
    await session.delete(signup)
    await session.flush()
    return True


async def due_reminders(session: AsyncSession) -> list[Reminder]:
    now = utcnow()
    result = await session.execute(
        select(Reminder)
        .join(Reminder.raid)
        .where(
            Reminder.sent.is_(False),
            Raid.cancelled.is_(False),
            Raid.archived.is_(False),
            Raid.message_id.is_not(None),
            Raid.starts_at - (Reminder.minutes_before * timedelta(minutes=1)) <= now,
            Raid.starts_at > now,
        )
        .options(selectinload(Reminder.raid).selectinload(Raid.signups).selectinload(RaidSignup.raid_class))
    )
    return list(result.scalars().all())


async def mark_reminder_sent(session: AsyncSession, reminder: Reminder) -> None:
    reminder.sent = True
    reminder.sent_at = utcnow()
    await session.flush()


async def update_raid(
    session: AsyncSession,
    raid: Raid,
    title: str | None = None,
    description: str | None | object = None,
    starts_at: datetime | None = None,
    reminder_minutes: int | None = None,
    mention_role_id: int | None | object = None,
    participant_limit: int | None = None,
) -> Raid:
    if title is not None:
        raid.title = title.strip()
    if description is not None:
        raid.description = description if isinstance(description, str) and description.strip() else None
    if starts_at is not None:
        raid.starts_at = starts_at
    if reminder_minutes is not None:
        raid.reminder_minutes = reminder_minutes
        for reminder in raid.reminders:
            await session.delete(reminder)
        await session.flush()
        if reminder_minutes > 0:
            session.add(Reminder(raid_id=raid.id, minutes_before=reminder_minutes, sent=False))
    if mention_role_id is not None:
        raid.mention_role_id = mention_role_id
    if participant_limit is not None:
        raid.participant_limit = participant_limit
    await session.flush()
    return raid
