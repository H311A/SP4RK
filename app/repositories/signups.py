import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import RaidSignup


async def get_signup(session: AsyncSession, raid_id: uuid.UUID, user_id: int) -> RaidSignup | None:
    stmt = select(RaidSignup).where(RaidSignup.raid_id == raid_id, RaidSignup.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_signup(
    session: AsyncSession,
    raid_id: uuid.UUID,
    user_id: int,
    display_name: str,
    class_id: uuid.UUID | None,
    status: str,
) -> RaidSignup:
    signup = await get_signup(session, raid_id, user_id)
    if signup is None:
        signup = RaidSignup(
            raid_id=raid_id, user_id=user_id, display_name=display_name, class_id=class_id, status=status
        )
        session.add(signup)
    else:
        signup.display_name = display_name
        signup.class_id = class_id
        signup.status = status
    await session.flush()
    return signup


async def delete_signup(session: AsyncSession, signup: RaidSignup) -> None:
    await session.delete(signup)


async def set_notifications(session: AsyncSession, signup: RaidSignup, enabled: bool) -> None:
    signup.notifications_enabled = enabled


async def list_backups_ordered(session: AsyncSession, raid_id: uuid.UUID) -> list[RaidSignup]:
    stmt = (
        select(RaidSignup)
        .where(RaidSignup.raid_id == raid_id, RaidSignup.status == "backup")
        .order_by(RaidSignup.joined_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
