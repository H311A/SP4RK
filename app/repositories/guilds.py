from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.models import Guild

async def ensure_guild(session: AsyncSession, guild_id: int, name: str) -> Guild:
    guild = await session.get(Guild, guild_id)
    if guild:
        if guild.name != name:
            guild.name = name
        return guild
    guild = Guild(id=guild_id, name=name)
    session.add(guild)
    await session.flush()
    return guild
