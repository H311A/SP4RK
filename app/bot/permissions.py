import discord

from app.database.session import SessionLocal
from app.repositories.admin_roles import is_admin_role


async def is_spark_admin(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild:
        return True
    role_ids = [role.id for role in member.roles]
    async with SessionLocal() as session:
        return await is_admin_role(session, interaction.guild_id, role_ids)


async def require_spark_admin(interaction: discord.Interaction) -> bool:
    if await is_spark_admin(interaction):
        return True
    from app.bot.ephemeral import send_ephemeral_followup

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    await send_ephemeral_followup(
        interaction,
        "Это действие доступно только администраторам SP4RK.",
    )
    return False
