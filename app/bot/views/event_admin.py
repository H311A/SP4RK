import discord

from app.bot import formatting as fmt
from app.bot.ephemeral import AutoExpireView, send_ephemeral_followup, show_screen
from app.bot.modals import NotifyNowModal, RescheduleModal, TemplateNameModal
from app.bot.state import EventDraft
from app.bot.views.confirm import ConfirmView
from app.bot.views.event_create import finalize_creation
from app.config import settings
from app.database.models import RaidSignup
from app.database.session import SessionLocal
from app.repositories.classes import list_classes
from app.repositories.raids import delete_raid, get_raid, list_active_raids, list_user_raids
from app.repositories.templates import create_template
from app.services import banners as banners_service
from app.services import events_calendar
from app.services import export as export_service
from app.services import signups as signups_service
from app.services.raids import refresh_raid_message
from app.utils.time import discord_ts

STATUS_LABELS = {
    "accepted": "в составе",
    "backup": "в запасе",
    "maybe": "возможно",
    "declined": "не пойдёшь",
}


async def send_my_events(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    async with SessionLocal() as session:
        raids = await list_user_raids(session, interaction.guild_id, interaction.user.id)

    embed = discord.Embed(title="Мои события", color=settings.brand_color)
    if not raids:
        embed.description = "Ты пока никуда не записан."
    else:
        lines = []
        for r in raids:
            signup = next((s for s in r.signups if s.user_id == interaction.user.id), None)
            status = STATUS_LABELS.get(signup.status if signup else "", "")
            link = f"https://discord.com/channels/{r.guild_id}/{r.channel_id}/{r.message_id}"
            lines.append(f"[{r.title}]({link}) - {discord_ts(r.starts_at, 'f')} - {status}")
        embed.description = "\n".join(lines)

    await send_ephemeral_followup(interaction, embed=embed)


async def _build_events_admin_screen(interaction: discord.Interaction) -> tuple[discord.Embed, "EventsAdminView"]:
    async with SessionLocal() as session:
        raids = await list_active_raids(session, interaction.guild_id)

    embed = discord.Embed(title="Управление событиями", color=settings.brand_color)
    if not raids:
        embed.description = "Активных событий нет."
    else:
        lines = [f"**{r.title}** - {discord_ts(r.starts_at, 'f')}" for r in raids]
        embed.description = "\n".join(lines)

    return embed, EventsAdminView(raids)


async def send_events_admin_menu(interaction: discord.Interaction) -> None:
    embed, view = await _build_events_admin_screen(interaction)
    await show_screen(interaction, embed=embed, view=view)


class EventsAdminView(AutoExpireView):
    def __init__(self, raids):
        super().__init__()
        if raids:
            self.add_item(RaidPickSelect(raids))

    @discord.ui.button(label="Назад к меню", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.main_menu import build_main_menu_embed, MainMenuView

        embed = build_main_menu_embed(interaction.guild.name)
        await show_screen(interaction, embed=embed, view=MainMenuView())


class RaidPickSelect(discord.ui.Select):
    def __init__(self, raids):
        options = [discord.SelectOption(label=r.title[:100], value=str(r.id)) for r in raids[:25]]
        super().__init__(placeholder="Событие…", options=options)
        self.raid_ids = {str(r.id): r.id for r in raids}

    async def callback(self, interaction: discord.Interaction) -> None:
        raid_id = self.raid_ids[self.values[0]]
        await send_raid_admin_detail(interaction, raid_id)


async def _build_raid_admin_screen(raid_id) -> tuple[discord.Embed, "RaidAdminDetailView"] | None:
    async with SessionLocal() as session:
        raid = await get_raid(session, raid_id)
    if raid is None:
        return None

    accepted = fmt.sorted_signups(raid.signups, "accepted")
    if raid.cancelled:
        status = "Отменено"
    elif raid.registration_closed:
        status = "Запись закрыта досрочно"
    else:
        status = "Открыто"

    embed = discord.Embed(title=raid.title, color=settings.brand_color)
    embed.add_field(name="Начало", value=discord_ts(raid.starts_at, "F"), inline=False)
    embed.add_field(
        name="Записано", value=f"{len(accepted)}/{fmt.limit_text(raid.participant_limit)}", inline=True
    )
    embed.add_field(name="Статус", value=status, inline=True)
    embed.add_field(name="​", value="​", inline=False)

    return embed, RaidAdminDetailView(raid_id)


async def send_raid_admin_detail(interaction: discord.Interaction, raid_id) -> None:
    built = await _build_raid_admin_screen(raid_id)
    if built is None:
        await show_screen(interaction, content="Событие не найдено.", embed=None, view=None)
        return
    embed, view = built
    await show_screen(interaction, embed=embed, view=view)


class RaidAdminDetailView(AutoExpireView):
    def __init__(self, raid_id):
        super().__init__()
        self.raid_id = raid_id

    @discord.ui.button(label="Назад к событиям", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        embed, view = await _build_events_admin_screen(interaction)
        await show_screen(interaction, embed=embed, view=view)

    @discord.ui.button(label="Закрыть/открыть запись", emoji="\U0001F512", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_close(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None:
                await show_screen(interaction, content="Событие не найдено.", embed=None, view=None)
                return
            raid.registration_closed = not raid.registration_closed
            await session.commit()
        await refresh_raid_message(interaction.client, self.raid_id)

        built = await _build_raid_admin_screen(self.raid_id)
        if built:
            embed, view = built
            await show_screen(interaction, embed=embed, view=view)

    @discord.ui.button(label="Изменить дату/время", emoji="\U0001F5D3️", style=discord.ButtonStyle.primary, row=0)
    async def reschedule(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        raid_id = self.raid_id

        async def on_new_datetime(inner_interaction: discord.Interaction, new_starts_at) -> None:
            async with SessionLocal() as session:
                raid = await get_raid(session, raid_id)
                if raid is None:
                    await inner_interaction.response.send_message("Событие не найдено.", ephemeral=True)
                    return
                old_starts_at = raid.starts_at
                raid.starts_at = new_starts_at
                signups = list(raid.signups)
                title = raid.title
                guild_id = raid.guild_id
                await session.commit()

            await refresh_raid_message(inner_interaction.client, raid_id)
            guild = inner_interaction.client.get_guild(guild_id)
            if guild is not None:
                async with SessionLocal() as session:
                    fresh = await get_raid(session, raid_id)
                    fresh.discord_event_id = await events_calendar.sync_scheduled_event(guild, fresh)
                    await session.commit()

            for s in signups:
                if s.status in ("accepted", "backup", "maybe") and s.notifications_enabled:
                    try:
                        user = await inner_interaction.client.fetch_user(s.user_id)
                        await user.send(
                            f"Время события **{title}** изменилось. "
                            f"Было: {discord_ts(old_starts_at, 'F')}. Стало: {discord_ts(new_starts_at, 'F')}."
                        )
                    except discord.HTTPException:
                        pass

            built = await _build_raid_admin_screen(raid_id)
            if built:
                embed, view = built
                await inner_interaction.response.edit_message(embed=embed, view=view)

        await interaction.response.send_modal(RescheduleModal("", on_new_datetime))

    @discord.ui.button(label="Отменить событие", emoji="\U0001F6AB", style=discord.ButtonStyle.danger, row=0)
    async def cancel_raid(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        raid_id = self.raid_id

        async def do_cancel(inner_interaction: discord.Interaction) -> None:
            async with SessionLocal() as session:
                raid = await get_raid(session, raid_id)
                if raid is None:
                    await show_screen(inner_interaction, content="Событие не найдено.", embed=None, view=None)
                    return
                signups = list(raid.signups)
                title = raid.title
                channel_id = raid.channel_id
                message_id = raid.message_id
                guild_id = raid.guild_id
                discord_event_id = raid.discord_event_id
                await delete_raid(session, raid)
                await session.commit()

            guild = inner_interaction.client.get_guild(guild_id)
            if guild is not None:
                await events_calendar.delete_scheduled_event(guild, discord_event_id)

            if channel_id and message_id:
                try:
                    channel = inner_interaction.client.get_channel(channel_id) or await inner_interaction.client.fetch_channel(
                        channel_id
                    )
                    message = await channel.fetch_message(message_id)
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

            for s in signups:
                if s.status in ("accepted", "backup", "maybe") and s.notifications_enabled:
                    try:
                        user = await inner_interaction.client.fetch_user(s.user_id)
                        await user.send(f"Событие **{title}** отменено.")
                    except discord.HTTPException:
                        pass

            embed, view = await _build_events_admin_screen(inner_interaction)
            await show_screen(inner_interaction, embed=embed, view=view)

        async def do_cancel_cancel(inner_interaction: discord.Interaction) -> None:
            built = await _build_raid_admin_screen(raid_id)
            if built:
                embed, view = built
                await show_screen(inner_interaction, embed=embed, view=view)

        await show_screen(
            interaction,
            content="Точно отменить событие? Всем записанным придёт уведомление.",
            embed=None,
            view=ConfirmView(on_confirm=do_cancel, on_cancel=do_cancel_cancel),
        )

    @discord.ui.button(label="Дублировать", emoji="\U0001F4C4", style=discord.ButtonStyle.secondary, row=1)
    async def duplicate(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None:
                await interaction.response.send_message("Событие не найдено.", ephemeral=True)
                return
            draft = EventDraft(
                guild_id=raid.guild_id,
                game_id=raid.game_id,
                title=raid.title,
                description=raid.description,
                participant_limit=raid.participant_limit,
                reminder_minutes=raid.reminder_minutes,
                duration_minutes=raid.duration_minutes,
                channel_id=raid.channel_id,
                mention_role_id=raid.mention_role_id,
                banner_path=banners_service.copy_banner(raid.banner_path),
            )

        async def on_datetime(inner_interaction: discord.Interaction, starts_at) -> None:
            draft.starts_at = starts_at
            await finalize_creation(inner_interaction, draft)

        await interaction.response.send_modal(RescheduleModal("", on_datetime))

    @discord.ui.button(label="Экспорт состава", emoji="\U0001F4E4", style=discord.ButtonStyle.secondary, row=1)
    async def export(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None:
                await send_ephemeral_followup(interaction, "Событие не найдено.")
                return
            classes = await list_classes(session, raid.game_id, active_only=False)
            file = export_service.build_roster_file(raid, classes)
        await interaction.followup.send(file=file, ephemeral=True)

    @discord.ui.button(label="Уведомить всех сейчас", emoji="\U0001F4E3", style=discord.ButtonStyle.primary, row=1)
    async def notify_now(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        raid_id = self.raid_id

        async def on_text(inner_interaction: discord.Interaction, custom_text: str | None) -> None:
            async with SessionLocal() as session:
                raid = await get_raid(session, raid_id)
                if raid is None:
                    await inner_interaction.response.send_message("Событие не найдено.", ephemeral=True)
                    return
                signups = list(raid.signups)
                title = raid.title

            sent = 0
            for s in signups:
                if s.status in ("accepted", "backup", "maybe") and s.notifications_enabled:
                    try:
                        user = await inner_interaction.client.fetch_user(s.user_id)
                        text = custom_text or f"Напоминание про **{title}**, загляни на карточку события."
                        await user.send(text)
                        sent += 1
                    except discord.HTTPException:
                        pass
            await inner_interaction.response.send_message(f"Отправлено {sent} сообщений.", ephemeral=True)

        await interaction.response.send_modal(NotifyNowModal(on_text))

    @discord.ui.button(label="Сохранить как шаблон", emoji="\U0001F4BE", style=discord.ButtonStyle.secondary, row=2)
    async def save_as_template(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        raid_id = self.raid_id
        user_id = interaction.user.id

        async def on_name(inner_interaction: discord.Interaction, name: str) -> None:
            async with SessionLocal() as session:
                raid = await get_raid(session, raid_id)
                if raid is None:
                    await inner_interaction.response.send_message("Событие не найдено.", ephemeral=True)
                    return
                await create_template(
                    session,
                    guild_id=raid.guild_id,
                    game_id=raid.game_id,
                    name=name,
                    title=raid.title,
                    description=raid.description,
                    channel_id=raid.channel_id,
                    mention_role_id=raid.mention_role_id,
                    reminder_minutes=raid.reminder_minutes,
                    participant_limit=raid.participant_limit,
                    duration_minutes=raid.duration_minutes,
                    banner_path=banners_service.copy_banner(raid.banner_path),
                    created_by=user_id,
                )
                await session.commit()
            await inner_interaction.response.send_message(f"Шаблон {name} сохранён.", ephemeral=True)

        await interaction.response.send_modal(TemplateNameModal(on_name))

    @discord.ui.button(label="Участники", emoji="\U0001F9F9", style=discord.ButtonStyle.secondary, row=2)
    async def manage_participants(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None:
                await show_screen(interaction, content="Событие не найдено.", embed=None, view=None)
                return
            members = list(raid.signups)
        if not members:
            await show_screen(interaction, content="Пока никто не записался.", embed=None, view=None)
            return
        note = " (показаны первые 25)" if len(members) > 25 else ""
        await show_screen(
            interaction,
            content=f"Кого убрать из события?{note}",
            embed=None,
            view=KickPickView(self.raid_id, members[:25]),
        )


class KickPickView(AutoExpireView):
    def __init__(self, raid_id, members):
        super().__init__()
        self.raid_id = raid_id
        self.add_item(KickSelect(raid_id, members))

    @discord.ui.button(label="Назад к событию", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        built = await _build_raid_admin_screen(self.raid_id)
        if built:
            embed, view = built
            await show_screen(interaction, embed=embed, view=view)


class KickSelect(discord.ui.Select):
    def __init__(self, raid_id, members):
        options = [
            discord.SelectOption(
                label=fmt.safe_display_name(m.display_name, m.user_id)[:100],
                description=STATUS_LABELS.get(m.status, ""),
                value=str(m.id),
            )
            for m in members
        ]
        super().__init__(placeholder="Участник…", options=options)
        self.raid_id = raid_id
        self.signup_ids = {str(m.id): m.id for m in members}

    async def callback(self, interaction: discord.Interaction) -> None:
        signup_id = self.signup_ids[self.values[0]]

        promoted_user_id = None
        raid_title = None
        async with SessionLocal() as session:
            signup = await session.get(RaidSignup, signup_id)
            if signup is not None:
                promoted = await signups_service.leave_and_promote(session, self.raid_id, signup)
                promoted_user_id = promoted.user_id if promoted else None
                raid = await get_raid(session, self.raid_id)
                raid_title = raid.title if raid else None
                await session.commit()

        await refresh_raid_message(interaction.client, self.raid_id)

        built = await _build_raid_admin_screen(self.raid_id)
        if built:
            embed, view = built
            await show_screen(interaction, embed=embed, view=view)

        if promoted_user_id:
            try:
                user = await interaction.client.fetch_user(promoted_user_id)
                await user.send(
                    f"Место освободилось: тебя перевели из запаса в основной состав на **{raid_title}**."
                )
            except discord.HTTPException:
                pass
