import types
import uuid
from datetime import datetime, timedelta

import discord
from sqlalchemy.exc import IntegrityError

from app.bot.banners.upload_flow import (
    BannerUploadCancelled,
    BannerUploadInvalid,
    BannerUploadTimeout,
    banner_hint_text,
    collect_image_via_dm,
)
from app.bot.constants import WEEKDAYS
from app.bot.ephemeral import AutoExpireView, schedule_delete_original, send_ephemeral_followup, show_screen
from app.bot.modals import EventParamsModal, RecurrenceTimeModal, RescheduleModal, TemplateBasicsModal
from app.bot.state import EventDraft
from app.bot.views.confirm import ConfirmView, ContinueToModalView
from app.bot.views.event_create import BannerChoiceView, ChannelRoleView, finalize_creation
from app.config import settings
from app.database.models import RaidTemplate
from app.database.session import SessionLocal
from app.repositories.classes import list_classes
from app.repositories.games import get_game, list_games
from app.repositories.guilds import ensure_guild
from app.repositories.templates import create_template, delete_template, list_templates
from app.services import banners as banners_service
from app.services.raids import build_message_payload


async def _build_templates_screen(interaction: discord.Interaction) -> tuple[discord.Embed, "TemplatesMenuView"]:
    async with SessionLocal() as session:
        templates = await list_templates(session, interaction.guild_id)

    embed = discord.Embed(title="Шаблоны", color=settings.brand_color)
    if not templates:
        embed.description = "Шаблонов пока нет."
    else:
        lines = []
        for t in templates:
            rec = " · повтор" if t.recurrence_enabled else ""
            lines.append(f"**{t.name}** - {t.title}{rec}")
        embed.description = "\n".join(lines)

    return embed, TemplatesMenuView(templates)


async def send_templates_menu(interaction: discord.Interaction) -> None:
    embed, view = await _build_templates_screen(interaction)
    await show_screen(interaction, embed=embed, view=view)


class TemplatesMenuView(AutoExpireView):
    def __init__(self, templates):
        super().__init__()
        if templates:
            self.add_item(TemplatePickSelect(templates))

    @discord.ui.button(label="Назад к меню", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.main_menu import build_main_menu_embed, MainMenuView

        embed = build_main_menu_embed(interaction.guild.name)
        await show_screen(interaction, embed=embed, view=MainMenuView())

    @discord.ui.button(label="Создать шаблон", emoji="➕", style=discord.ButtonStyle.primary, row=1)
    async def create_template_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = interaction.guild
        async with SessionLocal() as session:
            games = await list_games(session, guild.id)
        if not games:
            await show_screen(interaction, content="Сначала добавь игру.", embed=None, view=None)
            return

        try:
            dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
        except discord.Forbidden:
            await show_screen(
                interaction,
                content=(
                    "Не получилось написать тебе в личные сообщения. Разреши личные сообщения "
                    "от участников сервера и попробуй снова."
                ),
                embed=None,
                view=None,
            )
            return

        draft = EventDraft(guild_id=guild.id)
        await dm_channel.send("Для какой игры шаблон?", view=_TemplateGameSelectView(draft, games))
        await show_screen(
            interaction, content="Отправила тебе дальнейшие шаги в личные сообщения.", embed=None, view=None
        )


class _TemplateGameSelectView(AutoExpireView):
    def __init__(self, draft: EventDraft, games):
        super().__init__()
        self.add_item(_TemplateGameSelect(draft, games))


class _TemplateGameSelect(discord.ui.Select):
    def __init__(self, draft: EventDraft, games):
        options = [discord.SelectOption(label=f"{g.icon} {g.name}"[:100], value=str(g.id)) for g in games[:25]]
        super().__init__(placeholder="Игра", options=options)
        self.draft = draft
        self.games_by_id = {str(g.id): g for g in games}

    async def callback(self, interaction: discord.Interaction) -> None:
        self.draft.game_id = self.games_by_id[self.values[0]].id
        await interaction.response.send_modal(TemplateBasicsModal(self.draft, _after_template_basics))


async def _after_template_basics(interaction: discord.Interaction, draft: EventDraft) -> None:
    await show_screen(
        interaction,
        content="Основное сохранено. Дальше - лимит состава, напоминание и длительность.",
        embed=None,
        view=ContinueToModalView(lambda: EventParamsModal(draft, _after_template_params)),
    )


async def _after_template_params(interaction: discord.Interaction, draft: EventDraft) -> None:
    guild = interaction.client.get_guild(draft.guild_id)
    await show_screen(
        interaction,
        content="Выбери канал и роль по умолчанию, потом Продолжить.",
        embed=None,
        view=ChannelRoleView(draft, guild, _after_template_channel_role),
    )


async def _after_template_channel_role(interaction: discord.Interaction, draft: EventDraft) -> None:
    await show_screen(
        interaction,
        content="Добавим баннер? Он будет фиксирован для этого шаблона и будет использоваться каждый раз.",
        embed=None,
        view=BannerChoiceView(draft, _finalize_template),
    )


async def _finalize_template(interaction: discord.Interaction, draft: EventDraft) -> None:
    guild = interaction.client.get_guild(draft.guild_id)
    async with SessionLocal() as session:
        await ensure_guild(session, guild.id, guild.name)
        await create_template(
            session,
            guild_id=guild.id,
            game_id=draft.game_id,
            name=draft.name,
            title=draft.title,
            description=draft.description,
            channel_id=draft.channel_id,
            mention_role_id=draft.mention_role_id,
            reminder_minutes=draft.reminder_minutes,
            participant_limit=draft.participant_limit,
            duration_minutes=draft.duration_minutes,
            banner_path=draft.banner_path,
            created_by=interaction.user.id,
        )
        await session.commit()
    await show_screen(interaction, content=f"Готово, шаблон **{draft.name}** сохранён.", embed=None, view=None)
    schedule_delete_original(interaction)


class TemplatePickSelect(discord.ui.Select):
    def __init__(self, templates):
        options = [discord.SelectOption(label=t.name[:100], value=str(t.id)) for t in templates[:25]]
        super().__init__(placeholder="Шаблон…", options=options)
        self.templates_by_id = {str(t.id): t for t in templates}

    async def callback(self, interaction: discord.Interaction) -> None:
        template = self.templates_by_id[self.values[0]]
        await send_template_detail(interaction, template)


async def _build_template_detail_screen(template_id) -> tuple[discord.Embed, "TemplateDetailView"] | None:
    async with SessionLocal() as session:
        template = await session.get(RaidTemplate, template_id)
    if template is None:
        return None

    embed = discord.Embed(title=template.name, description=template.title, color=settings.brand_color)
    if template.recurrence_enabled:
        day_label = dict(WEEKDAYS).get(template.recurrence_day_of_week, "?")
        embed.add_field(
            name="Повтор",
            value=f"{day_label} в {template.recurrence_time}, публикация за {template.recurrence_lead_days} дн.",
            inline=False,
        )
    return embed, TemplateDetailView(template)


async def send_template_detail(interaction: discord.Interaction, template: RaidTemplate) -> None:
    built = await _build_template_detail_screen(template.id)
    if built is None:
        await show_screen(interaction, content="Шаблон не найден.", embed=None, view=None)
        return
    embed, view = built
    await show_screen(interaction, embed=embed, view=view)


async def _send_template_preview(interaction: discord.Interaction, template: RaidTemplate) -> None:
    async with SessionLocal() as session:
        game = await get_game(session, template.game_id)
        classes = await list_classes(session, template.game_id, active_only=False)

    starts_at = datetime.utcnow() + timedelta(hours=1)
    fake_raid = types.SimpleNamespace(
        id=uuid.uuid4(),
        title=template.title,
        description=template.description,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=template.duration_minutes),
        reminder_minutes=template.reminder_minutes,
        participant_limit=template.participant_limit,
        signups=[],
        cancelled=False,
        archived=False,
        registration_closed=False,
        banner_path=template.banner_path,
        game=game,
    )

    _main_embed, embeds, files = build_message_payload(fake_raid, classes)

    try:
        dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
        await dm_channel.send(
            content=(
                f"Так будет выглядеть событие из шаблона **{template.name}** "
                "(время и статус тут условные, для примера)."
            ),
            embeds=embeds,
            files=files,
        )
    except discord.Forbidden:
        await send_ephemeral_followup(
            interaction,
            "Не получилось написать тебе в личные сообщения. Разреши личные сообщения "
            "от участников сервера и попробуй снова.",
        )
        return

    await send_ephemeral_followup(interaction, "Отправила превью шаблона тебе в личные сообщения.")


class TemplateDetailView(AutoExpireView):
    def __init__(self, template: RaidTemplate):
        super().__init__()
        self.template = template

    @discord.ui.button(label="Назад к шаблонам", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        embed, view = await _build_templates_screen(interaction)
        await show_screen(interaction, embed=embed, view=view)

    @discord.ui.button(label="Создать событие из шаблона", emoji="\U0001F3AF", style=discord.ButtonStyle.primary, row=1)
    async def create_from_template(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        draft = EventDraft(
            guild_id=self.template.guild_id,
            game_id=self.template.game_id,
            template_id=self.template.id,
            title=self.template.title,
            description=self.template.description,
            participant_limit=self.template.participant_limit,
            reminder_minutes=self.template.reminder_minutes,
            duration_minutes=self.template.duration_minutes,
            channel_id=self.template.channel_id,
            mention_role_id=self.template.mention_role_id,
            banner_path=self.template.banner_path,
        )

        async def on_datetime(inner_interaction: discord.Interaction, starts_at) -> None:
            draft.starts_at = starts_at
            await finalize_creation(inner_interaction, draft)

        await interaction.response.send_modal(RescheduleModal("", on_datetime))

    @discord.ui.button(label="Показать шаблон", emoji="\U0001F441️", style=discord.ButtonStyle.secondary, row=1)
    async def preview_template(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await _send_template_preview(interaction, self.template)

    @discord.ui.button(label="Настроить повтор", emoji="\U0001F501", style=discord.ButtonStyle.secondary, row=1)
    async def configure_recurrence(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await show_screen(
            interaction, content="Выбери день недели:", embed=None, view=_WeekdaySelectView(self.template)
        )

    @discord.ui.button(label="Отключить повтор", emoji="⏹️", style=discord.ButtonStyle.secondary, row=1)
    async def disable_recurrence(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async with SessionLocal() as session:
            template = await session.get(RaidTemplate, self.template.id)
            if template:
                template.recurrence_enabled = False
                await session.commit()

        built = await _build_template_detail_screen(self.template.id)
        if built:
            embed, view = built
            await show_screen(interaction, embed=embed, view=view)

    @discord.ui.button(label="Изменить", emoji="\U0001F4DD", style=discord.ButtonStyle.secondary, row=2)
    async def edit_template(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        template_id = self.template.id
        draft = EventDraft(
            name=self.template.name,
            title=self.template.title,
            description=self.template.description,
        )

        async def on_submit(inner_interaction: discord.Interaction, updated_draft: EventDraft) -> None:
            async with SessionLocal() as session:
                template = await session.get(RaidTemplate, template_id)
                if template is None:
                    await inner_interaction.response.send_message("Шаблон не найден.", ephemeral=True)
                    return
                template.name = updated_draft.name
                template.title = updated_draft.title
                template.description = updated_draft.description
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    await inner_interaction.response.send_message(
                        "Шаблон с таким названием уже есть, выбери другое.", ephemeral=True
                    )
                    return

            built = await _build_template_detail_screen(template_id)
            if built:
                embed, view = built
                await inner_interaction.response.edit_message(embed=embed, view=view)

        await interaction.response.send_modal(TemplateBasicsModal(draft, on_submit))

    @discord.ui.button(label="Изменить баннер", emoji="\U0001F5BC️", style=discord.ButtonStyle.secondary, row=2)
    async def change_banner(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        template_id = self.template.id

        await interaction.response.edit_message(
            content="Пришли новую картинку баннера в личные сообщения.", embed=None, view=None
        )

        try:
            raw = await collect_image_via_dm(interaction.client, interaction.user, banner_hint_text())
        except (BannerUploadTimeout, BannerUploadCancelled):
            await show_screen(interaction, content="Не стала менять баннер.", embed=None, view=None)
            return
        except BannerUploadInvalid as exc:
            await show_screen(interaction, content=str(exc), embed=None, view=None)
            return

        path, _w, _h = banners_service.process_and_store(raw)

        async with SessionLocal() as session:
            template = await session.get(RaidTemplate, template_id)
            if template is None:
                banners_service.delete_banner(path)
                await show_screen(interaction, content="Шаблон уже удалён.", embed=None, view=None)
                return
            old_path = template.banner_path
            template.banner_path = path
            await session.commit()

        if old_path:
            banners_service.delete_banner(old_path)

        built = await _build_template_detail_screen(template_id)
        if built:
            embed, view = built
            await show_screen(interaction, embed=embed, view=view)
        else:
            await show_screen(interaction, content="Шаблон не найден.", embed=None, view=None)

    @discord.ui.button(label="Удалить шаблон", emoji="\U0001F5D1️", style=discord.ButtonStyle.danger, row=2)
    async def delete_template_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        template_id = self.template.id
        template_name = self.template.name

        async def do_delete(inner_interaction: discord.Interaction) -> None:
            async with SessionLocal() as session:
                template = await session.get(RaidTemplate, template_id)
                if template:
                    await delete_template(session, template)
                    await session.commit()
            embed, view = await _build_templates_screen(inner_interaction)
            await show_screen(inner_interaction, embed=embed, view=view)

        async def do_cancel(inner_interaction: discord.Interaction) -> None:
            built = await _build_template_detail_screen(template_id)
            if built:
                embed, view = built
                await show_screen(inner_interaction, embed=embed, view=view)

        await show_screen(
            interaction,
            content=f"Удалить шаблон {template_name}?",
            embed=None,
            view=ConfirmView(on_confirm=do_delete, on_cancel=do_cancel),
        )


class _WeekdaySelectView(AutoExpireView):
    def __init__(self, template: RaidTemplate):
        super().__init__()
        self.add_item(_WeekdaySelect(template))


class _WeekdaySelect(discord.ui.Select):
    def __init__(self, template: RaidTemplate):
        options = [discord.SelectOption(label=label, value=str(day)) for day, label in WEEKDAYS]
        super().__init__(placeholder="День недели", options=options)
        self.template = template

    async def callback(self, interaction: discord.Interaction) -> None:
        day = int(self.values[0])
        template_id = self.template.id

        async def on_time(inner_interaction: discord.Interaction, time_value: str, lead_days: int) -> None:
            async with SessionLocal() as session:
                template = await session.get(RaidTemplate, template_id)
                if template:
                    template.recurrence_enabled = True
                    template.recurrence_day_of_week = day
                    template.recurrence_time = time_value
                    template.recurrence_lead_days = lead_days
                    await session.commit()
            built = await _build_template_detail_screen(template_id)
            if built:
                embed, view = built
                await inner_interaction.response.edit_message(embed=embed, view=view)

        await interaction.response.send_modal(RecurrenceTimeModal(on_time))
