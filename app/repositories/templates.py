import uuid
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import RaidTemplate


async def create_template(
    session: AsyncSession,
    guild_id: int,
    name: str,
    title: str,
    description: str | None,
    channel_id: int,
    mention_role_id: int | None,
    reminder_minutes: int,
    participant_limit: int,
    created_by: int,
) -> RaidTemplate:
    template = RaidTemplate(
        guild_id=guild_id,
        name=name.strip(),
        title=title.strip(),
        description=description.strip() if description else None,
        channel_id=channel_id,
        mention_role_id=mention_role_id,
        reminder_minutes=reminder_minutes,
        participant_limit=participant_limit,
        created_by=created_by,
    )
    session.add(template)
    await session.flush()
    return template


async def list_templates(session: AsyncSession, guild_id: int) -> list[RaidTemplate]:
    result = await session.execute(
        select(RaidTemplate)
        .where(RaidTemplate.guild_id == guild_id)
        .order_by(RaidTemplate.created_at.desc(), RaidTemplate.name.asc())
    )
    return list(result.scalars().all())


async def get_template_by_prefix(session: AsyncSession, guild_id: int, template_id: str) -> RaidTemplate | None:
    templates = await list_templates(session, guild_id)
    matches = [t for t in templates if str(t.id).startswith(template_id.strip())]
    if len(matches) == 1:
        return matches[0]
    return None


async def delete_template_by_prefix(session: AsyncSession, guild_id: int, template_id: str) -> bool:
    template = await get_template_by_prefix(session, guild_id, template_id)
    if not template:
        return False
    await session.delete(template)
    await session.flush()
    return True


async def get_template(session: AsyncSession, guild_id: int, template_id: uuid.UUID) -> RaidTemplate | None:
    result = await session.execute(select(RaidTemplate).where(RaidTemplate.guild_id == guild_id, RaidTemplate.id == template_id))
    return result.scalar_one_or_none()


async def delete_template(session: AsyncSession, guild_id: int, template_id: uuid.UUID) -> RaidTemplate | None:
    template = await get_template(session, guild_id, template_id)
    if not template:
        return None
    await session.delete(template)
    await session.flush()
    return template
