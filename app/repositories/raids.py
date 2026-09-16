import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Raid, RaidSignup, Reminder

RAID_LOAD_OPTS = (
    selectinload(Raid.signups).selectinload(RaidSignup.raid_class),
    selectinload(Raid.reminders),
    selectinload(Raid.game),
)


async def create_raid(session: AsyncSession, **kwargs) -> Raid:
    raid = Raid(**kwargs)
    session.add(raid)
    await session.flush()
    return raid


async def get_raid(session: AsyncSession, raid_id: uuid.UUID) -> Raid | None:
    stmt = select(Raid).where(Raid.id == raid_id).options(*RAID_LOAD_OPTS)
    result = await session.execute(stmt)
    return result.unique().scalar_one_or_none()


async def get_raid_by_message_id(session: AsyncSession, message_id: int) -> Raid | None:
    stmt = select(Raid).where(Raid.message_id == message_id).options(*RAID_LOAD_OPTS)
    result = await session.execute(stmt)
    return result.unique().scalar_one_or_none()


async def list_active_raids(session: AsyncSession, guild_id: int) -> list[Raid]:
    stmt = (
        select(Raid)
        .where(Raid.guild_id == guild_id, Raid.archived.is_(False), Raid.cancelled.is_(False))
        .order_by(Raid.starts_at)
        .options(*RAID_LOAD_OPTS)
    )
    result = await session.execute(stmt)
    return list(result.unique().scalars().all())


async def list_raids_for_view_restore(session: AsyncSession, guild_id: int) -> list[Raid]:
    stmt = (
        select(Raid)
        .where(Raid.guild_id == guild_id, Raid.cancelled.is_(False), Raid.message_id.is_not(None))
        .options(*RAID_LOAD_OPTS)
    )
    result = await session.execute(stmt)
    return list(result.unique().scalars().all())


async def list_user_raids(session: AsyncSession, guild_id: int, user_id: int) -> list[Raid]:
    stmt = (
        select(Raid)
        .join(RaidSignup, RaidSignup.raid_id == Raid.id)
        .where(
            Raid.guild_id == guild_id,
            RaidSignup.user_id == user_id,
            Raid.archived.is_(False),
            Raid.cancelled.is_(False),
        )
        .order_by(Raid.starts_at)
        .options(*RAID_LOAD_OPTS)
    )
    result = await session.execute(stmt)
    return list(result.unique().scalars().all())


async def find_overlapping_raids(
    session: AsyncSession,
    guild_id: int,
    channel_id: int,
    starts_at: datetime,
    ends_at: datetime,
    exclude_raid_id: uuid.UUID | None = None,
) -> list[Raid]:
    stmt = select(Raid).where(
        Raid.guild_id == guild_id,
        Raid.channel_id == channel_id,
        Raid.cancelled.is_(False),
        Raid.archived.is_(False),
        Raid.starts_at < ends_at,
    )
    if exclude_raid_id is not None:
        stmt = stmt.where(Raid.id != exclude_raid_id)
    result = await session.execute(stmt)
    raids = list(result.scalars().all())
    return [r for r in raids if r.ends_at > starts_at]


async def due_reminders(session: AsyncSession) -> list[Reminder]:
    now = datetime.utcnow()
    stmt = (
        select(Reminder)
        .join(Raid, Reminder.raid_id == Raid.id)
        .where(Reminder.sent.is_(False), Raid.cancelled.is_(False))
        .options(selectinload(Reminder.raid).selectinload(Raid.signups).selectinload(RaidSignup.raid_class))
    )
    result = await session.execute(stmt)
    reminders = list(result.scalars().all())
    return [r for r in reminders if r.raid.starts_at - timedelta(minutes=r.minutes_before) <= now]


async def mark_reminder_sent(session: AsyncSession, reminder: Reminder) -> None:
    reminder.sent = True
    reminder.sent_at = datetime.utcnow()


async def due_raids_to_archive(session: AsyncSession) -> list[Raid]:
    now = datetime.utcnow()
    stmt = (
        select(Raid)
        .where(Raid.archived.is_(False), Raid.cancelled.is_(False), Raid.starts_at <= now)
        .options(*RAID_LOAD_OPTS)
    )
    result = await session.execute(stmt)
    return list(result.unique().scalars().all())


async def archive_raid(session: AsyncSession, raid: Raid) -> None:
    raid.archived = True


async def old_raids_to_purge(session: AsyncSession) -> list[Raid]:
    now = datetime.utcnow()
    stmt = select(Raid).where((Raid.archived.is_(True)) | (Raid.cancelled.is_(True))).options(*RAID_LOAD_OPTS)
    result = await session.execute(stmt)
    raids = list(result.unique().scalars().all())
    threshold = timedelta(hours=settings.raid_purge_after_hours)
    return [r for r in raids if r.ends_at + threshold <= now]


async def delete_raid(session: AsyncSession, raid: Raid) -> None:
    await session.delete(raid)


async def has_active_raids_for_game(session: AsyncSession, game_id: uuid.UUID) -> bool:
    stmt = (
        select(Raid.id)
        .where(Raid.game_id == game_id, Raid.archived.is_(False), Raid.cancelled.is_(False))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.first() is not None


async def list_active_raid_ids_for_game(session: AsyncSession, game_id: uuid.UUID) -> list:
    stmt = select(Raid.id).where(
        Raid.game_id == game_id, Raid.archived.is_(False), Raid.cancelled.is_(False)
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]
