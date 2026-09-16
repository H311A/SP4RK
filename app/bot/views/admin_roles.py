import discord

from app.bot.ephemeral import AutoExpireView, show_screen
from app.config import settings
from app.database.session import SessionLocal
from app.repositories.admin_roles import add_admin_role, list_admin_roles, remove_admin_role


async def _build_admin_roles_screen(interaction: discord.Interaction) -> tuple[discord.Embed, "AdminRolesView"]:
    async with SessionLocal() as session:
        roles = await list_admin_roles(session, interaction.guild_id)

    embed = discord.Embed(title="Роли администраторов SP4RK", color=settings.brand_color)
    if not roles:
        embed.description = (
            "Дополнительных ролей нет. Управлять ботом уже могут администраторы "
            "сервера и те, у кого есть право \"Управлять сервером\"."
        )
    else:
        lines = [f"<@&{r.role_id}>" for r in roles]
        embed.description = "\n".join(lines)

    return embed, AdminRolesView(roles)


async def send_admin_roles_menu(interaction: discord.Interaction) -> None:
    embed, view = await _build_admin_roles_screen(interaction)
    await show_screen(interaction, embed=embed, view=view)


class AdminRolesView(AutoExpireView):
    def __init__(self, roles):
        super().__init__()
        self.role_select = discord.ui.RoleSelect(
            placeholder="Добавить роль администратора", min_values=1, max_values=1
        )
        self.role_select.callback = self._on_add
        self.add_item(self.role_select)
        if roles:
            self.add_item(RemoveRoleSelect(roles))

    @discord.ui.button(label="Назад к меню", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.main_menu import build_main_menu_embed, MainMenuView

        embed = build_main_menu_embed(interaction.guild.name)
        await show_screen(interaction, embed=embed, view=MainMenuView())

    async def _on_add(self, interaction: discord.Interaction) -> None:
        role = self.role_select.values[0]
        async with SessionLocal() as session:
            existing = await list_admin_roles(session, interaction.guild_id)
            if not any(r.role_id == role.id for r in existing):
                await add_admin_role(session, interaction.guild_id, role.id, role.name, interaction.user.id)
                await session.commit()

        embed, view = await _build_admin_roles_screen(interaction)
        await show_screen(interaction, embed=embed, view=view)


class RemoveRoleSelect(discord.ui.Select):
    def __init__(self, roles):
        options = [discord.SelectOption(label=r.role_name[:100], value=str(r.role_id)) for r in roles[:25]]
        super().__init__(placeholder="Убрать роль…", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        role_id = int(self.values[0])
        async with SessionLocal() as session:
            await remove_admin_role(session, interaction.guild_id, role_id)
            await session.commit()

        embed, view = await _build_admin_roles_screen(interaction)
        await show_screen(interaction, embed=embed, view=view)
