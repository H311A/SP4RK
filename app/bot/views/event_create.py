from datetime import timedelta

import discord

from app.bot.banners.upload_flow import (
    BannerUploadCancelled,
    BannerUploadInvalid,
    BannerUploadTimeout,
    banner_hint_text,
    collect_image_via_dm,
)
from app.bot.ephemeral import AutoExpireView, schedule_delete_original, send_ephemeral_followup, show_screen
from app.bot.modals import EventBasicsModal, EventParamsModal
from app.bot.state import EventDraft
from app.bot.views.confirm import ConfirmView, ContinueToModalView
from app.database.models import Reminder
from app.database.session import SessionLocal
from app.repositories import raids as raids_repo
from app.repositories.classes import list_classes
from app.repositories.games import list_games
from app.repositories.guilds import ensure_guild
from app.services import banners as banners_service
from app.services import events_calendar
from app.services.raids import build_message_payload


async def start_event_creation(interaction: discord.Interaction) -> None:
    guild = interaction.guild

    try:
        dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
    except discord.Forbidden:
        await interaction.response.send_message(
            "Не получилось написать тебе в личные сообщения. Разреши личные сообщения от "
            "участников сервера в настройках приватности Discord и попробуй снова.",
            ephemeral=True,
        )
        return

    async with SessionLocal() as session:
        await ensure_guild(session, guild.id, guild.name)
        games = await list_games(session, guild.id)
        await session.commit()

    if not games:
        await interaction.response.send_message(
            "Сначала добавь хотя бы одну игру через раздел \"Игры и классы\".", ephemeral=True
        )
        return

    draft = EventDraft(guild_id=guild.id)
    view = GameSelectView(draft, games, _after_game_selected)
    await dm_channel.send("Для какой игры создаём событие?", view=view)

    if not interaction.response.is_done():
        await interaction.response.send_message(
            "Отправила тебе дальнейшие шаги в личные сообщения.", ephemeral=True
        )
    else:
        await interaction.edit_original_response(
            content="Отправила тебе дальнейшие шаги в личные сообщения.", embed=None, view=None
        )


class GameSelectView(AutoExpireView):
    def __init__(self, draft: EventDraft, games, on_selected):
        super().__init__()
        self.add_item(_GameSelect(draft, games, on_selected))


class _GameSelect(discord.ui.Select):
    def __init__(self, draft: EventDraft, games, on_selected):
        options = [discord.SelectOption(label=f"{g.icon} {g.name}"[:100], value=str(g.id)) for g in games[:25]]
        super().__init__(placeholder="Игра", options=options)
        self.draft = draft
        self.games_by_id = {str(g.id): g for g in games}
        self.on_selected = on_selected

    async def callback(self, interaction: discord.Interaction) -> None:
        self.draft.game_id = self.games_by_id[self.values[0]].id
        await self.on_selected(interaction, self.draft)


async def _after_game_selected(interaction: discord.Interaction, draft: EventDraft) -> None:
    await interaction.response.send_modal(EventBasicsModal(draft, _after_basics))


async def _after_basics(interaction: discord.Interaction, draft: EventDraft) -> None:
    await show_screen(
        interaction,
        content="Основное сохранено. Дальше - лимит состава, напоминание и длительность.",
        embed=None,
        view=ContinueToModalView(lambda: EventParamsModal(draft, _after_params)),
    )


async def _after_params(interaction: discord.Interaction, draft: EventDraft) -> None:
    guild = interaction.client.get_guild(draft.guild_id)
    await show_screen(
        interaction,
        content="Выбери канал для карточки события и, если нужно, роль для упоминания. Потом нажми Продолжить.",
        embed=None,
        view=ChannelRoleView(draft, guild, _after_channel_role),
    )


def _channel_options(guild: discord.Guild) -> list[discord.SelectOption]:
    postable = [c for c in guild.text_channels if c.permissions_for(guild.me).send_messages]
    postable.sort(key=lambda c: (c.category.position if c.category else -1, c.position))
    return [discord.SelectOption(label=f"#{c.name}"[:100], value=str(c.id)) for c in postable[:25]]


def _role_options(guild: discord.Guild) -> list[discord.SelectOption]:
    roles = [r for r in guild.roles if not r.is_default() and not r.managed]
    roles.sort(key=lambda r: r.position, reverse=True)
    return [discord.SelectOption(label=r.name[:100], value=str(r.id)) for r in roles[:25]]


class ChannelRoleView(AutoExpireView):
    def __init__(self, draft: EventDraft, guild: discord.Guild, on_continue):
        super().__init__()
        self.draft = draft
        self.on_continue = on_continue

        channel_options = _channel_options(guild)
        if channel_options:
            self.channel_select = discord.ui.Select(placeholder="Канал", options=channel_options)
            self.channel_select.callback = self._on_channel
            self.add_item(self.channel_select)

        role_options = _role_options(guild)
        if role_options:
            self.role_select = discord.ui.Select(
                placeholder="Роль для упоминания (необязательно)", options=role_options, row=1
            )
            self.role_select.callback = self._on_role
            self.add_item(self.role_select)

    async def _on_channel(self, interaction: discord.Interaction) -> None:
        self.draft.channel_id = int(self.channel_select.values[0])
        await interaction.response.defer()

    async def _on_role(self, interaction: discord.Interaction) -> None:
        self.draft.mention_role_id = int(self.role_select.values[0])
        await interaction.response.defer()

    @discord.ui.button(label="Продолжить", style=discord.ButtonStyle.primary, emoji="➡️", row=2)
    async def continue_(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not self.draft.channel_id:
            await interaction.response.send_message("Сначала выбери канал.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.on_continue(interaction, self.draft)


async def _after_channel_role(interaction: discord.Interaction, draft: EventDraft) -> None:
    await show_screen(
        interaction,
        content="Добавим баннер под карточку события?",
        embed=None,
        view=BannerChoiceView(draft, finalize_creation),
    )


class BannerChoiceView(AutoExpireView):
    def __init__(self, draft: EventDraft, on_done):
        super().__init__()
        self.draft = draft
        self.on_done = on_done

    @discord.ui.button(label="Загрузить баннер", emoji="\U0001F5BC️", style=discord.ButtonStyle.primary)
    async def upload(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.defer()
        try:
            raw = await collect_image_via_dm(interaction.client, interaction.user, banner_hint_text())
        except BannerUploadTimeout:
            await send_ephemeral_followup(interaction, "Не дождалась картинки, создаю событие без баннера.")
            await self.on_done(interaction, self.draft)
            return
        except BannerUploadCancelled:
            await send_ephemeral_followup(interaction, "Загрузка отменена, создаю событие без баннера.")
            await self.on_done(interaction, self.draft)
            return
        except BannerUploadInvalid as exc:
            await send_ephemeral_followup(interaction, str(exc))
            await self.on_done(interaction, self.draft)
            return

        path, _w, _h = banners_service.process_and_store(raw)
        self.draft.banner_path = path
        await send_ephemeral_followup(interaction, "Баннер готов.")
        await self.on_done(interaction, self.draft)

    @discord.ui.button(label="Без баннера", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.defer()
        await self.on_done(interaction, self.draft)


async def finalize_creation(interaction: discord.Interaction, draft: EventDraft) -> None:
    ends_at = draft.starts_at + timedelta(minutes=draft.duration_minutes)
    async with SessionLocal() as session:
        overlaps = await raids_repo.find_overlapping_raids(
            session, draft.guild_id, draft.channel_id, draft.starts_at, ends_at
        )

    if overlaps:
        names = ", ".join(r.title for r in overlaps)

        async def proceed(inner_interaction: discord.Interaction) -> None:
            await _create_and_post(inner_interaction, draft)

        await show_screen(
            interaction,
            content=f"В это время в этом канале уже есть событие: {names}. Всё равно создать?",
            embed=None,
            view=ConfirmView(
                on_confirm=proceed, confirm_label="Создать всё равно", confirm_style=discord.ButtonStyle.primary
            ),
        )
        return

    await _create_and_post(interaction, draft)


async def _create_and_post(interaction: discord.Interaction, draft: EventDraft) -> None:
    guild = interaction.client.get_guild(draft.guild_id)

    async with SessionLocal() as session:
        await ensure_guild(session, guild.id, guild.name)
        raid = await raids_repo.create_raid(
            session,
            guild_id=guild.id,
            game_id=draft.game_id,
            template_id=draft.template_id,
            title=draft.title,
            description=draft.description,
            starts_at=draft.starts_at,
            duration_minutes=draft.duration_minutes,
            channel_id=draft.channel_id,
            created_by=interaction.user.id,
            reminder_minutes=draft.reminder_minutes,
            mention_role_id=draft.mention_role_id,
            participant_limit=draft.participant_limit,
            banner_path=draft.banner_path,
        )
        session.add(Reminder(raid_id=raid.id, minutes_before=draft.reminder_minutes))
        await session.flush()
        classes = await list_classes(session, draft.game_id, active_only=False)
        raid_id = raid.id
        await session.commit()

    channel = guild.get_channel(draft.channel_id) or await interaction.client.fetch_channel(draft.channel_id)

    from app.bot.views.signup import build_signup_view

    async with SessionLocal() as session:
        fresh_raid = await raids_repo.get_raid(session, raid_id)
        _main_embed, embeds, files = build_message_payload(fresh_raid, classes)

    view = build_signup_view(raid_id, classes, disabled=False)
    content = f"<@&{draft.mention_role_id}>" if draft.mention_role_id else None
    message = await channel.send(content=content, embeds=embeds, files=files, view=view)

    async with SessionLocal() as session:
        db_raid = await raids_repo.get_raid(session, raid_id)
        db_raid.message_id = message.id
        db_raid.discord_event_id = await events_calendar.sync_scheduled_event(guild, db_raid)
        await session.commit()

    await show_screen(interaction, content=f"Готово, событие опубликовано в {channel.mention}.", embed=None, view=None)
    schedule_delete_original(interaction)
