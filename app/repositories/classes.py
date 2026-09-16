import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import GameClass


async def create_class(
    session: AsyncSession,
    game_id: uuid.UUID,
    name: str,
    icon: str,
    limit_count: int,
    created_by: int,
    parent_class_id: uuid.UUID | None = None,
    role: str | None = None,
) -> GameClass:
    cls = GameClass(
        game_id=game_id,
        name=name.strip(),
        icon=icon or "⚡",
        limit_count=limit_count,
        created_by=created_by,
        parent_class_id=parent_class_id,
        role=role,
    )
    session.add(cls)
    await session.flush()
    return cls


async def list_classes(
    session: AsyncSession, game_id: uuid.UUID, active_only: bool = True, top_level_only: bool = False
) -> list[GameClass]:
    stmt = select(GameClass).where(GameClass.game_id == game_id)
    if active_only:
        stmt = stmt.where(GameClass.is_active.is_(True))
    if top_level_only:
        stmt = stmt.where(GameClass.parent_class_id.is_(None))
    stmt = stmt.order_by(GameClass.sort_order, GameClass.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_specs(session: AsyncSession, class_id: uuid.UUID, active_only: bool = True) -> list[GameClass]:
    stmt = select(GameClass).where(GameClass.parent_class_id == class_id)
    if active_only:
        stmt = stmt.where(GameClass.is_active.is_(True))
    stmt = stmt.order_by(GameClass.sort_order, GameClass.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_class(session: AsyncSession, class_id: uuid.UUID) -> GameClass | None:
    return await session.get(GameClass, class_id)


async def set_class_role(session: AsyncSession, cls: GameClass, role: str | None) -> None:
    cls.role = role


async def delete_class(session: AsyncSession, cls: GameClass) -> None:
    await session.delete(cls)
