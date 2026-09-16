import discord
from discord import app_commands

from app.bot.permissions import is_spark_admin
from app.bot.views.main_menu import MainMenuView, build_main_menu_embed
from app.database.session import SessionLocal
from app.repositories.guilds import ensure_guild


@app_commands.command(name="spark", description="Открыть меню SP4RK (только для администраторов)")
async def spark_command(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "Эта команда работает только на сервере.", ephemeral=True
        )
        return

    if not await is_spark_admin(interaction):
        await interaction.response.send_message(
            "Меню SP4RK доступно только администраторам.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)
    async with SessionLocal() as session:
        await ensure_guild(session, interaction.guild_id, interaction.guild.name)
        await session.commit()

    embed = build_main_menu_embed(interaction.guild.name)
    view = MainMenuView()
    await interaction.edit_original_response(embed=embed, view=view)
    view.bind(interaction)


def setup_commands(bot: discord.Client) -> None:
    bot.tree.add_command(spark_command)
