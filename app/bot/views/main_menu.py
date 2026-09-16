import discord

from app.bot.ephemeral import AutoExpireView
from app.config import settings


def build_main_menu_embed(guild_name: str) -> discord.Embed:
    return discord.Embed(
        title="SP4RK",
        description=f"Меню событий гильдии {guild_name}. Всё управление - кнопками ниже.",
        color=settings.brand_color,
    )


class MainMenuView(AutoExpireView):
    def __init__(self):
        super().__init__()

    @discord.ui.button(label="Создать событие", emoji="\U0001F5D3️", style=discord.ButtonStyle.primary, row=0)
    async def create_event(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.event_create import start_event_creation

        await start_event_creation(interaction)

    @discord.ui.button(label="Игры и классы", emoji="\U0001F3AE", style=discord.ButtonStyle.secondary, row=0)
    async def games(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.games import send_games_menu

        await send_games_menu(interaction)

    @discord.ui.button(label="Шаблоны", emoji="\U0001F9E9", style=discord.ButtonStyle.secondary, row=0)
    async def templates(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.templates import send_templates_menu

        await send_templates_menu(interaction)

    @discord.ui.button(label="Управление событиями", emoji="\U0001F5C2️", style=discord.ButtonStyle.secondary, row=1)
    async def manage_events(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.event_admin import send_events_admin_menu

        await send_events_admin_menu(interaction)

    @discord.ui.button(label="Роли админов", emoji="\U0001F6E1️", style=discord.ButtonStyle.secondary, row=1)
    async def admin_roles(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.admin_roles import send_admin_roles_menu

        await send_admin_roles_menu(interaction)

    @discord.ui.button(label="Статистика", emoji="\U0001F4CA", style=discord.ButtonStyle.secondary, row=2)
    async def stats(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.settings import send_stats

        await send_stats(interaction)

    @discord.ui.button(label="Логи", emoji="\U0001F4DC", style=discord.ButtonStyle.secondary, row=2)
    async def logs(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.settings import send_logs

        await send_logs(interaction)
