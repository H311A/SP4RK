from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AttendanceRecord, Raid


async def snapshot_raid_attendance(session: AsyncSession, raid: Raid) -> None:
    game_name = raid.game.name if raid.game else ""
    for signup in raid.signups:
        session.add(
            AttendanceRecord(
                guild_id=raid.guild_id,
                game_name=game_name,
                raid_id=raid.id,
                raid_title=raid.title,
                starts_at=raid.starts_at,
                user_id=signup.user_id,
                display_name=signup.display_name,
                class_name=(signup.raid_class.name if signup.raid_class else None),
                final_status=signup.status,
            )
        )


async def user_stats(session: AsyncSession, guild_id: int, user_id: int) -> dict[str, int]:
    stmt = (
        select(AttendanceRecord.final_status, func.count())
        .where(AttendanceRecord.guild_id == guild_id, AttendanceRecord.user_id == user_id)
        .group_by(AttendanceRecord.final_status)
    )
    result = await session.execute(stmt)
    return {status: count for status, count in result.all()}


async def top_attendees(session: AsyncSession, guild_id: int, limit: int = 10) -> list[tuple[int, str, int]]:
    stmt = (
        select(AttendanceRecord.user_id, func.max(AttendanceRecord.display_name), func.count())
        .where(AttendanceRecord.guild_id == guild_id, AttendanceRecord.final_status == "accepted")
        .group_by(AttendanceRecord.user_id)
        .order_by(func.count().desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.all())


async def most_cancelled(session: AsyncSession, guild_id: int, limit: int = 10) -> list[tuple[int, str, int]]:
    stmt = (
        select(AttendanceRecord.user_id, func.max(AttendanceRecord.display_name), func.count())
        .where(AttendanceRecord.guild_id == guild_id, AttendanceRecord.final_status == "declined")
        .group_by(AttendanceRecord.user_id)
        .order_by(func.count().desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.all())
