from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.database.models import GuildAdminRole


async def list_admin_roles(session: AsyncSession, guild_id: int) -> list[GuildAdminRole]:
    result = await session.execute(
        select(GuildAdminRole)
        .where(GuildAdminRole.guild_id == guild_id)
        .order_by(GuildAdminRole.role_name.asc())
    )
    return list(result.scalars().all())


async def add_admin_role(
    session: AsyncSession,
    guild_id: int,
    role_id: int,
    role_name: str,
    added_by: int,
) -> GuildAdminRole:
    role = GuildAdminRole(
        guild_id=guild_id,
        role_id=role_id,
        role_name=role_name,
        added_by=added_by,
    )
    session.add(role)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        result = await session.execute(
            select(GuildAdminRole).where(
                GuildAdminRole.guild_id == guild_id,
                GuildAdminRole.role_id == role_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        raise
    return role


async def delete_admin_role(session: AsyncSession, guild_id: int, role_id: int) -> bool:
    result = await session.execute(
        delete(GuildAdminRole).where(
            GuildAdminRole.guild_id == guild_id,
            GuildAdminRole.role_id == role_id,
        )
    )
    await session.flush()
    return bool(result.rowcount)


async def admin_role_ids(session: AsyncSession, guild_id: int) -> set[int]:
    roles = await list_admin_roles(session, guild_id)
    return {role.role_id for role in roles}
