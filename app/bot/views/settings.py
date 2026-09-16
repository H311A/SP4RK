import os

import discord

from app.bot.ephemeral import send_ephemeral_followup
from app.config import settings
from app.database.session import SessionLocal
from app.services import stats as stats_service


async def send_stats(interaction: discord.Interaction) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    async with SessionLocal() as session:
        text = await stats_service.build_top_text(session, interaction.guild_id)

    embed = discord.Embed(title="Статистика посещаемости", description=text, color=settings.brand_color)
    embed.set_footer(text="Считается по итогам событий, которые уже завершились.")
    await send_ephemeral_followup(interaction, embed=embed)


async def send_logs(interaction: discord.Interaction) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    if not os.path.isfile(settings.log_file):
        await send_ephemeral_followup(interaction, "Файл логов пока пуст.")
        return
    await interaction.followup.send(file=discord.File(settings.log_file), ephemeral=True)
