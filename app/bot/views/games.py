import discord

from app.bot.ephemeral import AutoExpireView, show_screen
from app.bot.modals import GameCreateModal
from app.config import settings
from app.database.session import SessionLocal
from app.repositories.games import create_game, list_games


async def _build_games_screen(interaction: discord.Interaction) -> tuple[discord.Embed, "GamesMenuView"]:
    async with SessionLocal() as session:
        games = await list_games(session, interaction.guild_id, active_only=False)

    embed = discord.Embed(title="Игры", color=settings.brand_color)
    if not games:
        embed.description = "Пока не добавлено ни одной игры."
    else:
        lines = []
        for g in games:
            state = "" if g.is_active else " (скрыта)"
            lines.append(f"{g.icon} **{g.name}**{state}")
        embed.description = "\n".join(lines)

    return embed, GamesMenuView(games)


async def send_games_menu(interaction: discord.Interaction) -> None:
    embed, view = await _build_games_screen(interaction)
    await show_screen(interaction, embed=embed, view=view)


class GamesMenuView(AutoExpireView):
    def __init__(self, games):
        super().__init__()
        if games:
            self.add_item(GamePickSelect(games))

    @discord.ui.button(label="Назад к меню", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.main_menu import build_main_menu_embed, MainMenuView

        embed = build_main_menu_embed(interaction.guild.name)
        await show_screen(interaction, embed=embed, view=MainMenuView())

    @discord.ui.button(label="Добавить игру", emoji="➕", style=discord.ButtonStyle.primary, row=1)
    async def add_game(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild_id = interaction.guild_id
        user_id = interaction.user.id

        async def on_submit(inner_interaction: discord.Interaction, name: str, icon: str) -> None:
            if not name:
                await inner_interaction.response.edit_message(
                    content="Название не может быть пустым.", embed=None, view=None
                )
                return
            async with SessionLocal() as session:
                await create_game(session, guild_id, name, icon, settings.brand_color, user_id)
                await session.commit()
            embed, view = await _build_games_screen(inner_interaction)
            await show_screen(inner_interaction, embed=embed, view=view)

        await interaction.response.send_modal(GameCreateModal(on_submit))


class GamePickSelect(discord.ui.Select):
    def __init__(self, games):
        options = [discord.SelectOption(label=f"{g.icon} {g.name}"[:100], value=str(g.id)) for g in games[:25]]
        super().__init__(placeholder="Выбери игру для управления", options=options)
        self.games_by_id = {str(g.id): g for g in games}

    async def callback(self, interaction: discord.Interaction) -> None:
        game = self.games_by_id[self.values[0]]
        from app.bot.views.classes import send_game_detail

        await send_game_detail(interaction, game)
