import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import RaidTemplate


async def create_template(session: AsyncSession, **kwargs) -> RaidTemplate:
    template = RaidTemplate(**kwargs)
    session.add(template)
    await session.flush()
    return template


async def list_templates(session: AsyncSession, guild_id: int) -> list[RaidTemplate]:
    stmt = select(RaidTemplate).where(RaidTemplate.guild_id == guild_id).order_by(RaidTemplate.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_template(session: AsyncSession, template_id: uuid.UUID) -> RaidTemplate | None:
    return await session.get(RaidTemplate, template_id)


async def delete_template(session: AsyncSession, template: RaidTemplate) -> None:
    await session.delete(template)


async def list_recurring_templates(session: AsyncSession) -> list[RaidTemplate]:
    stmt = select(RaidTemplate).where(RaidTemplate.recurrence_enabled.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_recurrence_run(session: AsyncSession, template: RaidTemplate, when: datetime) -> None:
    template.last_recurrence_run = when
