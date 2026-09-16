from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import GuildAdminRole


async def add_admin_role(
    session: AsyncSession, guild_id: int, role_id: int, role_name: str, added_by: int
) -> GuildAdminRole:
    row = GuildAdminRole(guild_id=guild_id, role_id=role_id, role_name=role_name, added_by=added_by)
    session.add(row)
    await session.flush()
    return row


async def remove_admin_role(session: AsyncSession, guild_id: int, role_id: int) -> bool:
    stmt = select(GuildAdminRole).where(GuildAdminRole.guild_id == guild_id, GuildAdminRole.role_id == role_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    return True


async def list_admin_roles(session: AsyncSession, guild_id: int) -> list[GuildAdminRole]:
    stmt = select(GuildAdminRole).where(GuildAdminRole.guild_id == guild_id).order_by(GuildAdminRole.role_name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def is_admin_role(session: AsyncSession, guild_id: int, role_ids: list[int]) -> bool:
    if not role_ids:
        return False
    stmt = select(GuildAdminRole.id).where(
        GuildAdminRole.guild_id == guild_id, GuildAdminRole.role_id.in_(role_ids)
    )
    result = await session.execute(stmt)
    return result.first() is not None
