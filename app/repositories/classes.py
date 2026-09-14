import uuid
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.database.models import RaidClass

async def create_class(session: AsyncSession, guild_id: int, name: str, icon: str, limit_count: int, created_by: int) -> RaidClass:
    class_name = name.strip()

    existing = await session.scalar(
        select(RaidClass).where(
            RaidClass.guild_id == guild_id,
            RaidClass.name == class_name,
        )
    )

    if existing:
        if existing.is_active:
            raise ValueError("Класс с таким названием уже существует.")

        max_order = await session.scalar(
            select(func.max(RaidClass.sort_order)).where(RaidClass.guild_id == guild_id)
        )
        existing.icon = icon
        existing.limit_count = limit_count
        existing.sort_order = (max_order or 0) + 1
        existing.created_by = created_by
        existing.is_active = True
        await session.flush()
        return existing

    max_order = await session.scalar(select(func.max(RaidClass.sort_order)).where(RaidClass.guild_id == guild_id))
    cls = RaidClass(
        guild_id=guild_id,
        name=class_name,
        icon=icon,
        limit_count=limit_count,
        sort_order=(max_order or 0) + 1,
        created_by=created_by,
        is_active=True,
    )
    session.add(cls)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise ValueError("Класс с таким названием уже существует.")
    return cls

async def list_classes(session: AsyncSession, guild_id: int) -> list[RaidClass]:
    result = await session.execute(
        select(RaidClass)
        .where(RaidClass.guild_id == guild_id, RaidClass.is_active.is_(True))
        .order_by(RaidClass.sort_order.asc(), RaidClass.name.asc())
    )
    return list(result.scalars().all())

async def get_class(session: AsyncSession, class_id: uuid.UUID) -> RaidClass | None:
    return await session.get(RaidClass, class_id)

async def delete_class_by_id(session: AsyncSession, guild_id: int, class_id: uuid.UUID) -> RaidClass | None:
    cls = await session.get(RaidClass, class_id)
    if not cls or cls.guild_id != guild_id or not cls.is_active:
        return None
    cls.is_active = False
    await session.flush()
    return cls
