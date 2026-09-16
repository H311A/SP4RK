import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Game


async def create_game(
    session: AsyncSession, guild_id: int, name: str, icon: str, color: int, created_by: int
) -> Game:
    game = Game(guild_id=guild_id, name=name.strip(), icon=icon or "\U0001F3AE", color=color, created_by=created_by)
    session.add(game)
    await session.flush()
    return game


async def list_games(session: AsyncSession, guild_id: int, active_only: bool = True) -> list[Game]:
    stmt = select(Game).where(Game.guild_id == guild_id)
    if active_only:
        stmt = stmt.where(Game.is_active.is_(True))
    stmt = stmt.order_by(Game.sort_order, Game.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_game(session: AsyncSession, game_id: uuid.UUID) -> Game | None:
    return await session.get(Game, game_id)


async def set_game_active(session: AsyncSession, game: Game, is_active: bool) -> None:
    game.is_active = is_active


async def set_game_color(session: AsyncSession, game: Game, color: int) -> None:
    game.color = color


async def delete_game(session: AsyncSession, game: Game) -> None:
    await session.delete(game)
