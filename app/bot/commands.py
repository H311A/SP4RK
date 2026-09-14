from datetime import datetime
import io
import logging
import os
import re
import uuid

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database.session import SessionLocal
from app.repositories.guilds import ensure_guild
from app.repositories import admin_roles as admin_role_repo
from app.repositories import classes as class_repo
from app.repositories import raids as raid_repo
from app.repositories import templates as template_repo
from app.services.raids import build_raid_embed, refresh_raid_message
from app.bot.ui import build_signup_view, DeleteClassView
from app.bot.ephemeral import send_ephemeral_followup
from app.utils.time import parse_moscow_datetime, discord_ts, short_id

EPHEMERAL_DELETE_AFTER = settings.ephemeral_delete_after
log = logging.getLogger("SP4RK.commands")
CUSTOM_EMOJI_RE = re.compile(r"^<a?:[A-Za-z0-9_]{2,32}:\d{17,22}>$")
COLON_EMOJI_RE = re.compile(r"^:([A-Za-z0-9_]{2,32}):$")


CUSTOM_EMOJI_ANY_RE = re.compile(r"<a?:([A-Za-z0-9_]{2,32}):(\d{17,22})>")


def _emoji_name_to_letter(name: str) -> str:
    clean = name.strip("_")
    match = re.search(r"letter([A-Za-z0-9])$", clean, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    if clean.upper().startswith("AAAAA") and len(clean) >= 6:
        return clean[-1].upper()
    if len(clean) == 1:
        return clean.upper()
    return ""


def select_raid_label(raid) -> str:
    # Select labels are plain text: custom emoji codes in event titles render badly
    # or break the dropdown. Keep the option stable and compact: only short ID.
    return f"ID {short_id(raid.id)}"


def require_guild(interaction: discord.Interaction) -> bool:
    return interaction.guild is not None


def normalize_emoji_name(class_name: str) -> str:
    value = class_name.replace("–", "-").replace("—", "-")
    value = re.sub(r"\s*-\s*", "_", value)
    value = re.sub(r"\s+", "_", value.strip())
    value = re.sub(r"[^A-Za-z0-9_]", "", value)
    return value


def find_emoji_by_name(interaction: discord.Interaction, emoji_name: str) -> str | None:
    if interaction.guild:
        for emoji in interaction.guild.emojis:
            if emoji.name == emoji_name:
                return f"<{'a' if emoji.animated else ''}:{emoji.name}:{emoji.id}>"
    for emoji in interaction.client.emojis:
        if emoji.name == emoji_name:
            return f"<{'a' if emoji.animated else ''}:{emoji.name}:{emoji.id}>"
    return None


def resolve_emoji(interaction: discord.Interaction, raw_icon: str | None, class_name: str) -> str:
    icon = (raw_icon or "").strip()
    if icon and CUSTOM_EMOJI_RE.match(icon):
        return icon
    if icon:
        match = COLON_EMOJI_RE.match(icon)
        if match:
            return find_emoji_by_name(interaction, match.group(1)) or icon
        return icon
    auto_name = normalize_emoji_name(class_name)
    return find_emoji_by_name(interaction, auto_name) or "✨"


def admin_embed(title: str, description: str, color: int = 0x7C5CFF) -> discord.Embed:
    embed = discord.Embed(title=f"{title}", description=description, color=color)
    embed.set_footer(text="SP4RK • Помощница гильдии Stormchasers.")
    return embed


async def _member_from_interaction(interaction: discord.Interaction) -> discord.Member | None:
    if not interaction.guild:
        return None
    if isinstance(interaction.user, discord.Member):
        return interaction.user
    try:
        return await interaction.guild.fetch_member(interaction.user.id)
    except Exception:
        return None


async def is_bot_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False

    member = interaction.user if isinstance(interaction.user, discord.Member) else await _member_from_interaction(interaction)

    # Discord передаёт права и роли пользователя прямо в slash-interaction.
    # Это работает даже без privileged Members Intent.
    perms = getattr(interaction, "permissions", None)
    if perms and (perms.administrator or perms.manage_guild):
        return True

    if member:
        member_perms = getattr(member, "guild_permissions", None)
        if member_perms and (member_perms.administrator or member_perms.manage_guild):
            return True

    async with SessionLocal() as session:
        role_ids = await admin_role_repo.admin_role_ids(session, interaction.guild.id)

    if not role_ids or not member:
        return False

    member_role_ids = {role.id for role in getattr(member, "roles", [])}
    return bool(member_role_ids.intersection(role_ids))


async def is_server_admin(interaction: discord.Interaction) -> bool:
    member = await _member_from_interaction(interaction)
    return bool(member and member.guild_permissions.administrator)


async def deny(interaction: discord.Interaction):
    await interaction.response.send_message(
        "❌ У тебя нет прав для администрирования SP4RK.",
        ephemeral=True,
        delete_after=EPHEMERAL_DELETE_AFTER,
    )


async def raid_message_exists(bot: discord.Client, raid) -> bool:
    if not raid.message_id:
        return False
    try:
        channel = bot.get_channel(raid.channel_id) or await bot.fetch_channel(raid.channel_id)
        await channel.fetch_message(raid.message_id)
        return True
    except (discord.NotFound, discord.Forbidden):
        return False


def _match_by_short_id(items, short: str):
    short = short.strip()
    matched = [item for item in items if str(item.id).startswith(short)]
    if len(matched) == 1:
        return matched[0], None
    if not matched:
        return None, "❌ Ничего не найдено. Проверь ID."
    return None, "❌ Найдено несколько совпадений. Укажи ID длиннее."


class CreateFromTemplateModal(discord.ui.Modal, title="Создание события из шаблона"):
    def __init__(self, cog: "SparkCommands", template_id: uuid.UUID, default_description: str | None):
        super().__init__(timeout=1800)
        self.cog = cog
        self.template_id = template_id
        self.starts_at = discord.ui.TextInput(
            label="Время события",
            placeholder="2026-06-07 21:00",
            required=True,
            max_length=16,
        )
        self.description = discord.ui.TextInput(
            label="Описание события",
            placeholder="Можно оставить описание из шаблона или изменить его.",
            default=default_description or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1800,
        )
        self.add_item(self.starts_at)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        async with SessionLocal() as session:
            template = await template_repo.get_template(session, interaction.guild.id, self.template_id)
        if not template:
            return await interaction.response.send_message("❌ Шаблон не найден.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        try:
            channel = interaction.guild.get_channel(template.channel_id) or await interaction.guild.fetch_channel(template.channel_id)
        except Exception:
            return await interaction.response.send_message("❌ Канал из шаблона не найден или недоступен для SP4RK.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        role = interaction.guild.get_role(template.mention_role_id) if template.mention_role_id else None
        await self.cog._create_raid_card(
            interaction,
            channel,
            template.title,
            str(self.starts_at.value),
            template.participant_limit,
            role,
            str(self.description.value or ""),
            template.reminder_minutes,
        )


class CreateFromTemplateSelect(discord.ui.Select):
    def __init__(self, cog: "SparkCommands", templates):
        self.cog = cog
        self.templates_by_id = {str(t.id): t for t in templates[:25]}
        options = [
            discord.SelectOption(
                label=f"ID {short_id(t.id)}",
                value=str(t.id),
                description=(f"Шаблон • лимит {t.participant_limit} • канал {t.channel_id}")[:100],
                emoji="📋",
            )
            for t in templates[:25]
        ]
        super().__init__(placeholder="Выбери шаблон события.", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        template = self.templates_by_id.get(self.values[0])
        if not template:
            return await interaction.response.send_message("❌ Шаблон не найден.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        await interaction.response.send_modal(CreateFromTemplateModal(self.cog, template.id, template.description))


class CreateFromTemplateView(discord.ui.View):
    def __init__(self, cog: "SparkCommands", templates):
        super().__init__(timeout=1800)
        self.add_item(CreateFromTemplateSelect(cog, templates))


class EditTemplateModal(discord.ui.Modal, title="Редактирование шаблона"):
    def __init__(self, template, channel_id: int | None = None, role_id: int | None = None):
        super().__init__(timeout=1800)
        self.template_id = template.id
        self.channel_id = channel_id
        self.role_id = role_id
        self.template_name_input = discord.ui.TextInput(
            label="Имя шаблона в списке",
            default=template.name or "",
            required=True,
            max_length=4000,
        )
        self.event_title_input = discord.ui.TextInput(
            label="Название события в шаблоне",
            default=template.title or "",
            required=True,
            max_length=4000,
        )
        self.description = discord.ui.TextInput(
            label="Описание",
            default=template.description or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1800,
        )
        self.participant_limit = discord.ui.TextInput(
            label="Лимит основного состава",
            default=str(template.participant_limit),
            required=True,
            max_length=3,
        )
        self.reminder = discord.ui.TextInput(
            label="Напоминание в минутах",
            default=str(template.reminder_minutes),
            required=True,
            max_length=4,
        )
        self.add_item(self.template_name_input)
        self.add_item(self.event_title_input)
        self.add_item(self.description)
        self.add_item(self.participant_limit)
        self.add_item(self.reminder)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            participant_limit = int(str(self.participant_limit.value).strip())
            reminder = int(str(self.reminder.value).strip())
        except ValueError:
            return await interaction.response.send_message("❌ Лимит и напоминание должны быть числами.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        if participant_limit < 1:
            return await interaction.response.send_message("❌ Лимит должен быть минимум 1.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        if reminder < 1:
            return await interaction.response.send_message("❌ Напоминание должно быть минимум за 1 минуту.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

        async with SessionLocal() as session:
            tmpl = await template_repo.get_template(session, interaction.guild.id, self.template_id)
            if not tmpl:
                return await interaction.response.send_message("❌ Шаблон не найден.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
            tmpl.name = str(self.template_name_input.value).strip()
            tmpl.title = str(self.event_title_input.value).strip()
            tmpl.description = str(self.description.value).strip() or None
            tmpl.participant_limit = participant_limit
            tmpl.reminder_minutes = reminder
            if self.channel_id is not None:
                tmpl.channel_id = self.channel_id
            if self.role_id is not None:
                tmpl.mention_role_id = self.role_id
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return await interaction.response.send_message("❌ Шаблон с таким именем уже существует.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        await interaction.response.send_message(embed=admin_embed("Шаблон изменён", "Шаблон обновлён."), ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)


class EditTemplateSelect(discord.ui.Select):
    def __init__(self, templates):
        self.templates_by_id = {str(t.id): t for t in templates[:25]}
        options = [
            discord.SelectOption(
                label=f"ID {short_id(t.id)}",
                value=str(t.id),
                description=(f"Шаблон • лимит {t.participant_limit}")[:100],
                emoji="✏️",
            )
            for t in templates[:25]
        ]
        super().__init__(placeholder="Выбери шаблон, который нужно изменить.", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        template = self.templates_by_id.get(self.values[0])
        if not template:
            return await interaction.response.send_message("❌ Шаблон не найден.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        await interaction.response.send_modal(EditTemplateModal(template))


class EditTemplateView(discord.ui.View):
    def __init__(self, templates):
        super().__init__(timeout=1800)
        self.add_item(EditTemplateSelect(templates))


class DeleteTemplateSelect(discord.ui.Select):
    def __init__(self, templates):
        options = [
            discord.SelectOption(
                label=f"ID {short_id(t.id)}",
                value=str(t.id),
                description=(f"Шаблон • лимит {t.participant_limit}")[:100],
                emoji="🗑️",
            )
            for t in templates[:25]
        ]
        super().__init__(placeholder="Выбери шаблон, который нужно удалить.", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        template_id = uuid.UUID(self.values[0])
        async with SessionLocal() as session:
            template = await template_repo.delete_template(session, interaction.guild.id, template_id)
            if template:
                name = template.name
            await session.commit()
        if not template:
            return await interaction.response.edit_message(content="❌ Шаблон уже удалён или не найден.", embed=None, view=None)
        await interaction.response.edit_message(content=f"🗑️  Шаблон **{name}** удалён.", embed=None, view=None)


class DeleteTemplateView(discord.ui.View):
    def __init__(self, templates):
        super().__init__(timeout=1800)
        self.add_item(DeleteTemplateSelect(templates))


class EditRaidModal(discord.ui.Modal, title="Редактирование события"):
    def __init__(self, cog: "SparkCommands", raid):
        super().__init__(timeout=1800)
        self.cog = cog
        self.raid_id = raid.id
        self.title_input = discord.ui.TextInput(
            label="Название события",
            default=raid.title or "",
            required=True,
            max_length=4000,
        )
        self.starts_at_input = discord.ui.TextInput(
            label="Время события",
            placeholder="2026-06-07 21:00",
            default=raid.starts_at.strftime("%Y-%m-%d %H:%M"),
            required=True,
            max_length=16,
        )
        self.description_input = discord.ui.TextInput(
            label="Описание события",
            default=raid.description or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1800,
        )
        self.participant_limit_input = discord.ui.TextInput(
            label="Лимит основного состава",
            default=str(raid.participant_limit or 1),
            required=True,
            max_length=3,
        )
        self.reminder_input = discord.ui.TextInput(
            label="Напоминание в минутах",
            default=str(raid.reminder_minutes or settings.default_reminder_minutes),
            required=True,
            max_length=4,
        )
        self.add_item(self.title_input)
        self.add_item(self.starts_at_input)
        self.add_item(self.description_input)
        self.add_item(self.participant_limit_input)
        self.add_item(self.reminder_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            starts_at = parse_moscow_datetime(str(self.starts_at_input.value).strip())
        except ValueError:
            return await interaction.response.send_message(
                "❌ Формат даты: `YYYY-MM-DD HH:MM`.",
                ephemeral=True,
                delete_after=EPHEMERAL_DELETE_AFTER,
            )

        try:
            participant_limit = int(str(self.participant_limit_input.value).strip())
            reminder = int(str(self.reminder_input.value).strip())
        except ValueError:
            return await interaction.response.send_message(
                "❌ Лимит и напоминание должны быть числами.",
                ephemeral=True,
                delete_after=EPHEMERAL_DELETE_AFTER,
            )

        if participant_limit < 1:
            return await interaction.response.send_message(
                "❌ Лимит должен быть минимум 1.",
                ephemeral=True,
                delete_after=EPHEMERAL_DELETE_AFTER,
            )
        if reminder < 1:
            return await interaction.response.send_message(
                "❌ Напоминание должно быть минимум за 1 минуту.",
                ephemeral=True,
                delete_after=EPHEMERAL_DELETE_AFTER,
            )

        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, self.raid_id)
            if not raid or raid.guild_id != interaction.guild.id or raid.cancelled:
                return await interaction.response.send_message(
                    "❌ Событие не найдено или уже удалено.",
                    ephemeral=True,
                    delete_after=EPHEMERAL_DELETE_AFTER,
                )
            if raid.archived and raid.starts_at > raid_repo.utcnow():
                raid.archived = False
            await raid_repo.update_raid(
                session,
                raid,
                title=str(self.title_input.value).strip(),
                description=str(self.description_input.value).strip(),
                starts_at=starts_at,
                reminder_minutes=reminder,
                participant_limit=participant_limit,
            )
            await session.commit()
            raid_id = raid.id

        await refresh_raid_message(self.cog.bot, raid_id)
        await interaction.response.send_message(
            embed=admin_embed("Событие изменено", f"Событие `{short_id(raid_id)}` обновлено. Записавшиеся участники сохранены."),
            ephemeral=True,
            delete_after=EPHEMERAL_DELETE_AFTER,
        )


class EditRaidSelect(discord.ui.Select):
    def __init__(self, cog: "SparkCommands", raids):
        self.cog = cog
        self.raids_by_id = {str(r.id): r for r in raids[:25]}
        options = []
        for r in raids[:25]:
            options.append(
                discord.SelectOption(
                    label=select_raid_label(r),
                    value=str(r.id),
                    description=(f"ID {short_id(r.id)} • {r.starts_at.strftime('%Y-%m-%d %H:%M')} • лимит {r.participant_limit or 0}")[:100],
                    emoji="✏️",
                )
            )
        super().__init__(placeholder="Выбери событие, которое нужно изменить.", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        raid = self.raids_by_id.get(self.values[0])
        if not raid:
            return await interaction.response.send_message(
                "❌ Событие не найдено.",
                ephemeral=True,
                delete_after=EPHEMERAL_DELETE_AFTER,
            )
        await interaction.response.send_modal(EditRaidModal(self.cog, raid))


class EditRaidView(discord.ui.View):
    def __init__(self, cog: "SparkCommands", raids):
        super().__init__(timeout=1800)
        self.add_item(EditRaidSelect(cog, raids))


class SparkCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    spark = app_commands.Group(name="spark", description="⚡ Администрирование SP4RK.")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        log.error("Slash command failed: %s", type(original).__name__, exc_info=(type(original), original, getattr(original, "__traceback__", None)))
        text = f"❌ Команда завершилась ошибкой: `{type(original).__name__}`. Подробности можно посмотреть через `/spark логи`."
        try:
            if interaction.response.is_done():
                await send_ephemeral_followup(interaction, text)
            else:
                await interaction.response.send_message(text, ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        except Exception:
            pass

    @spark.command(name="помощь", description="Показать справку по SP4RK.")
    async def help_cmd(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        embed = admin_embed(
            "Справка",
            (
                "Участникам не нужны команды - запись проходит только через кнопки в карточке события.\n\n"
                "**Классы:**\n"
                "`/spark класс-добавить` — добавить класс.\n"
                "`/spark класс-удалить` — открыть меню удаления класса.\n"
                "`/spark класс-показать-все` — показать классы.\n\n"
                "**События:**\n"
                "`/spark событие-создать` — создать событие.\n"
                "`/spark событие-создать-из-шаблона` — выбрать шаблон, затем указать время и описание.\n"
                "`/spark событие-показать-все` — показать активные события.\n"
                "`/spark событие-редактировать` — изменить событие.\n"
                "`/spark событие-удалить` — удалить событие.\n\n"
                "**Шаблоны:**\n"
                "`/spark шаблон-создать` — создать новый шаблон.\n"
		"`/spark шаблон-показать-все` — показать все созданные шаблоны.\n"
		" `/spark шаблон-редактировать` — выбрать шаблон из списка и изменить его.\n"
		" `/spark шаблон-удалить` — удалить шаблон.\n\n"
                "**Права:**\n"
                "`/spark роль-админа-добавить` — добавить группу администраторов по роли.\n" 
		"`/spark роль-админа-удалить` — удалить группу администраторов по роли.\n" 
		"`/spark роль-админа-показать-все` — показать все группы администраторов.\n\n"
                "`/spark логи` — скачать файл ошибок."
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

    @spark.command(name="роль-админа-добавить", description="Разрешить роли администрировать SP4RK.")
    @app_commands.describe(роль="Роль, которая сможет создавать события и управлять ботом.")
    async def admin_role_add(self, interaction: discord.Interaction, роль: discord.Role):
        if not await is_server_admin(interaction):
            return await interaction.response.send_message("❌ Эту настройку может менять только администратор сервера.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        async with SessionLocal() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            await admin_role_repo.add_admin_role(session, interaction.guild.id, роль.id, роль.name, interaction.user.id)
            await session.commit()
        await interaction.response.send_message(embed=admin_embed("Роль добавлена.", f"Роль {роль.mention} теперь может администрировать SP4RK."), ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

    @spark.command(name="роль-админа-удалить", description="Запретить роли администрировать SP4RK.")
    @app_commands.describe(роль="Роль, которую нужно убрать из администраторов SP4RK.")
    async def admin_role_delete(self, interaction: discord.Interaction, роль: discord.Role):
        if not await is_server_admin(interaction):
            return await interaction.response.send_message("❌ Эту настройку может менять только администратор сервера.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        async with SessionLocal() as session:
            deleted = await admin_role_repo.delete_admin_role(session, interaction.guild.id, роль.id)
            await session.commit()
        text = f"Роль {роль.mention} больше не администрирует SP4RK." if deleted else "Этой роли нет в списке администраторов SP4RK."
        await interaction.response.send_message(embed=admin_embed("Роль удалена.", text), ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

    @spark.command(name="роль-админа-показать-все", description="Показать роли, которым разрешено управлять SP4RK.")
    async def admin_role_list(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        async with SessionLocal() as session:
            roles = await admin_role_repo.list_admin_roles(session, interaction.guild.id)
        text = "Дополнительных ролей пока нет. По умолчанию SP4RK управляют администраторы сервера и пользователи с правом «Управлять сервером»." if not roles else "\n".join(f"• <@&{role.role_id}>" for role in roles)
        await interaction.response.send_message(embed=admin_embed("Роли администрирования.", text), ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

    @spark.command(name="класс-добавить", description="Добавить класс с иконкой и лимитом участников.")
    @app_commands.describe(название="Название класса", лимит="Лимит мест для класса. 0 = без лимита.", иконка="Необязательно: 🌑, :Bellstrike_Umbra: или <:Bellstrike_Umbra:ID>")
    async def class_add(self, interaction: discord.Interaction, название: str, лимит: int = 0, иконка: str = ""):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        if лимит < 0:
            return await interaction.response.send_message("❌ Лимит не может быть меньше 0.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        class_name = название.strip()
        resolved_icon = resolve_emoji(interaction, иконка, class_name)
        async with SessionLocal() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            try:
                raid_class = await class_repo.create_class(session, interaction.guild.id, class_name, resolved_icon, лимит, interaction.user.id)
                await session.commit()
            except (ValueError, IntegrityError):
                await session.rollback()
                return await interaction.response.send_message("❌ Класс с таким названием уже существует.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        embed = admin_embed("Класс добавлен", f"{raid_class.icon} **{raid_class.name}**\n\nЛимит участников: **{raid_class.limit_count or 'без лимита'}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

    @spark.command(name="класс-удалить", description="Открыть меню удаления класса.")
    async def class_delete(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        async with SessionLocal() as session:
            raid_classes = await class_repo.list_classes(session, interaction.guild.id)
        if not raid_classes:
            return await interaction.response.send_message("Классов пока нет.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        await interaction.response.send_message(embed=admin_embed("Удаление класса", "Выберите класс из списка ниже."), view=DeleteClassView(raid_classes), ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

    @spark.command(name="класс-показать-все", description="Показать классы, доступные для записи.")
    async def class_list(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        async with SessionLocal() as session:
            raid_classes = await class_repo.list_classes(session, interaction.guild.id)
        if not raid_classes:
            return await interaction.response.send_message("Классов пока нет. Добавь первый класс через `/spark класс-добавить`.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        lines = [f"{index}. {c.icon} **{c.name}** — лимит: **{c.limit_count or 'без лимита'}**." for index, c in enumerate(raid_classes, start=1)]
        await interaction.response.send_message(embed=admin_embed("Классы", "\n".join(lines)[:4000]), ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

    async def _create_raid_card(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, starts_at: str, participant_limit: int, role: discord.Role | None, description: str, reminder: int):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            dt = parse_moscow_datetime(starts_at)
        except ValueError:
            return await send_ephemeral_followup(interaction, "❌ Укажи дату в формате `YYYY-MM-DD HH:MM`, например `2026-06-07 21:00` по Москве.")
        if dt <= datetime.utcnow():
            return await send_ephemeral_followup(interaction, "❌ Дата события должна быть в будущем.")
        if reminder < 1:
            return await send_ephemeral_followup(interaction, "❌ Напоминание должно быть минимум за 1 минуту.")
        if participant_limit < 1:
            return await send_ephemeral_followup(interaction, "❌ Лимит участников должен быть минимум 1.")
        if (dt - datetime.utcnow()).total_seconds() <= 60:
            return await send_ephemeral_followup(interaction, "❌ До события должно быть больше 1 минуты, иначе регистрация сразу будет закрыта.")

        async with SessionLocal() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            raid_classes = await class_repo.list_classes(session, interaction.guild.id)
            if not raid_classes:
                return await send_ephemeral_followup(interaction, "Сначала добавь хотя бы один класс через `/spark класс-добавить`.")
            raid = await raid_repo.create_raid(
                session=session,
                guild_id=interaction.guild.id,
                title=title.strip(),
                description=description.strip() or None,
                starts_at=dt,
                channel_id=channel.id,
                created_by=interaction.user.id,
                reminder_minutes=reminder,
                mention_role_id=role.id if role else None,
                participant_limit=int(participant_limit),
            )
            await session.commit()
            raid = await raid_repo.get_raid(session, raid.id)

        content = role.mention if role else None
        allowed_mentions = discord.AllowedMentions(roles=True) if role else discord.AllowedMentions.none()
        try:
            message = await channel.send(content=content, embed=build_raid_embed(raid, raid_classes), view=build_signup_view(raid.id, raid_classes), allowed_mentions=allowed_mentions)
        except discord.Forbidden:
            return await send_ephemeral_followup(interaction, f"❌ SP4RK не может отправить сообщение в {channel.mention}. Проверь права: Просмотр канала, Отправка сообщений, Встраивание ссылок.")

        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, raid.id)
            await raid_repo.set_raid_message(session, raid, message.id)
            await session.commit()
        await send_ephemeral_followup(interaction, f"✅ Карточка события отправлена в {channel.mention}: `{short_id(raid.id)}` • {discord_ts(dt, 'F')}.")

    @spark.command(name="событие-создать", description="Создать карточку события с кнопками записи.")
    @app_commands.rename(channel="канал", title="название", starts_at="время", participant_limit="лимит", role="тег", description="описание", reminder="напоминание")
    @app_commands.describe(channel="Канал, куда SP4RK отправит карточку события.", title="Название события", starts_at="Дата по Москве: YYYY-MM-DD HH:MM", participant_limit="Обязательный лимит основного состава", role="Роль для уведомления", description="Описание события", reminder="За сколько минут до начала напомнить в ЛС. По умолчанию 30 минут")
    async def raid_create(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, starts_at: str, participant_limit: app_commands.Range[int, 1, 999], role: discord.Role | None = None, description: str = "", reminder: int = settings.default_reminder_minutes):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        return await self._create_raid_card(interaction, channel, title, starts_at, int(participant_limit), role, description, reminder)

    @spark.command(name="событие-показать-все", description="Показать активные события.")
    async def raid_list(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with SessionLocal() as session:
            raids = await raid_repo.list_active_raids(session, interaction.guild.id)
            alive = []
            for raid in raids:
                if await raid_message_exists(self.bot, raid):
                    alive.append(raid)
                else:
                    await raid_repo.delete_raid(session, raid)
            await session.commit()
        if not alive:
            return await send_ephemeral_followup(interaction, "Активных событий нет.")
        lines = [f"• `{short_id(r.id)}` — **{r.title}** — {discord_ts(r.starts_at, 'f')}." for r in alive[:20]]
        await send_ephemeral_followup(interaction, embed=admin_embed("Активные события", "\n".join(lines)))

    @spark.command(name="событие-удалить", description="Удалить событие по короткому или полному ID.")
    @app_commands.describe(событие_id="ID события из карточки. Можно указать первые 8 символов.")
    async def raid_delete(self, interaction: discord.Interaction, событие_id: str):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        async with SessionLocal() as session:
            raids = await raid_repo.list_active_raids(session, interaction.guild.id)
            raid, err = _match_by_short_id(raids, событие_id)
            if err:
                return await interaction.response.send_message(err, ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
            message_id = raid.message_id
            channel_id = raid.channel_id
            await raid_repo.delete_raid(session, raid)
            await session.commit()
        if message_id:
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                msg = await channel.fetch_message(message_id)
                await msg.delete()
            except Exception:
                pass
        await interaction.response.send_message(embed=admin_embed("Событие удалено", f"Событие `{событие_id}` удалено."), ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

    @spark.command(name="событие-редактировать", description="Выбрать событие из списка и изменить карточку.")
    async def raid_edit(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        async with SessionLocal() as session:
            raids = await raid_repo.list_active_raids(session, interaction.guild.id)
        if not raids:
            return await interaction.response.send_message(
                "Активных событий нет.",
                ephemeral=True,
                delete_after=EPHEMERAL_DELETE_AFTER,
            )
        await interaction.response.send_message(
            embed=admin_embed(
                "Редактирование события",
                "Выбери событие из списка ниже. Потом SP4RK откроет форму, где можно спокойно изменить название, описание, время, лимит и напоминание. Записавшиеся участники сохранятся.",
            ),
            view=EditRaidView(self, raids),
            ephemeral=True,
        )

    @spark.command(name="шаблон-создать", description="Создать шаблон события без отправки карточки.")
    @app_commands.rename(name="имя", channel="канал", title="название", participant_limit="лимит", role="тег", description="описание", reminder="напоминание")
    @app_commands.describe(name="Название шаблона в списке.", channel="Канал будущей карточки события.", title="Название события.", participant_limit="Лимит основного состава.", role="Роль для упоминания при создании события.", description="Описание события", reminder="За сколько минут напомнить в ЛС")
    async def template_create(self, interaction: discord.Interaction, name: str, channel: discord.TextChannel, title: str, participant_limit: app_commands.Range[int, 1, 999], role: discord.Role | None = None, description: str = "", reminder: int = settings.default_reminder_minutes):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        if reminder < 1:
            return await send_ephemeral_followup(interaction, "❌ Напоминание должно быть минимум за 1 минуту.")
        async with SessionLocal() as session:
            await ensure_guild(session, interaction.guild.id, interaction.guild.name)
            try:
                tmpl = await template_repo.create_template(
                    session,
                    interaction.guild.id,
                    name,
                    title,
                    description,
                    channel.id,
                    role.id if role else None,
                    int(reminder),
                    int(participant_limit),
                    interaction.user.id,
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return await send_ephemeral_followup(interaction, "❌ Шаблон с таким именем уже существует.")
        await send_ephemeral_followup(
            interaction,
            embed=admin_embed(
                "Шаблон создан",
                f"`{short_id(tmpl.id)}` — **{tmpl.name}**.\n\nКарточка события не создавалась. Шаблон появился в списке для `/spark событие-создать-из-шаблона`.",
            ),
        )

    @spark.command(name="шаблон-показать-все", description="Показать все шаблоны событий.")
    async def template_list(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        async with SessionLocal() as session:
            templates = await template_repo.list_templates(session, interaction.guild.id)
        if not templates:
            return await interaction.response.send_message("Шаблонов пока нет.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        lines = [f"• `{short_id(t.id)}` — **{t.name}**: {t.title}, лимит **{t.participant_limit}**, канал <#{t.channel_id}>." for t in templates[:25]]
        await interaction.response.send_message(embed=admin_embed("Шаблоны", "\n".join(lines)), ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

    @spark.command(name="шаблон-редактировать", description="Выбрать шаблон из списка и отредактировать.")
    async def template_edit(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        async with SessionLocal() as session:
            templates = await template_repo.list_templates(session, interaction.guild.id)
        if not templates:
            return await interaction.response.send_message("Шаблонов пока нет.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        await interaction.response.send_message(
            embed=admin_embed("Редактирование шаблона", "Выбери шаблон из списка ниже. После выбора SP4RK откроет форму редактирования."),
            view=EditTemplateView(templates),
            ephemeral=True,
        )

    @spark.command(name="шаблон-удалить", description="Удалить шаблон через выпадающий список.")
    async def template_delete(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        async with SessionLocal() as session:
            templates = await template_repo.list_templates(session, interaction.guild.id)
        if not templates:
            return await interaction.response.send_message("Шаблонов пока нет.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        await interaction.response.send_message(
            embed=admin_embed("Удаление шаблона", "Выберите шаблон из списка ниже."),
            view=DeleteTemplateView(templates),
            ephemeral=True,
        )

    @spark.command(name="событие-создать-из-шаблона", description="Выбрать шаблон, затем указать время и описание.")
    async def raid_create_from_template(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        async with SessionLocal() as session:
            templates = await template_repo.list_templates(session, interaction.guild.id)
        if not templates:
            return await interaction.response.send_message("Шаблонов пока нет. Создай шаблон через `/spark шаблон-создать`.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        await interaction.response.send_message(
            embed=admin_embed("Создание из шаблона", "Сначала выбери шаблон из списка ниже. Потом SP4RK откроет форму, где нужно указать время и описание события."),
            view=CreateFromTemplateView(self, templates),
            ephemeral=True,
        )

    @spark.command(name="логи", description="Скачать файл ошибок SP4RK.")
    async def error_logs(self, interaction: discord.Interaction):
        if not await is_bot_admin(interaction):
            return await deny(interaction)
        path = settings.log_file
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return await interaction.response.send_message("Файл ошибок пока пуст.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
        with open(path, "rb") as f:
            data = f.read()[-512_000:]
        file = discord.File(io.BytesIO(data), filename="sp4rk_errors.txt")
        await interaction.response.send_message("Последние ошибки SP4RK:", file=file, ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)


async def setup_commands(bot: commands.Bot) -> None:
    await bot.add_cog(SparkCommands(bot))
