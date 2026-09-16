import asyncio
import logging

import discord

from app.bot import formatting as fmt
from app.bot.ephemeral import send_ephemeral_followup
from app.bot.faq import send_faq_hint
from app.bot.permissions import is_spark_admin
from app.bot.views.help import send_faq_hub
from app.database.session import SessionLocal
from app.repositories.classes import get_class, list_classes, list_specs
from app.repositories.raids import get_raid
from app.repositories.signups import get_signup
from app.services import signups as signups_service
from app.services.raids import build_roster_breakdown_embed, refresh_raid_message

log = logging.getLogger("SP4RK.signup")


def _spawn_refresh(client: discord.Client, raid_id) -> None:
    async def runner() -> None:
        try:
            await refresh_raid_message(client, raid_id)
        except Exception:
            log.exception("Could not refresh raid card for %s", raid_id)

    asyncio.create_task(runner())


async def _try_reuse_existing_class(session, raid, user_id: int):
    signup = await get_signup(session, raid.id, user_id)
    if signup is None or not signup.class_id:
        return None
    return await get_class(session, signup.class_id)


async def _notify_backup_position(client: discord.Client, raid_id, user_id: int) -> None:
    async with SessionLocal() as session:
        position = await signups_service.get_backup_position(session, raid_id, user_id)
    if position is None:
        return
    try:
        user = await client.fetch_user(user_id)
        await user.send(
            f"Ты в запасе под номером {position}. Как только освободится место, "
            "автоматически переведу тебя в основной состав."
        )
    except discord.HTTPException:
        pass


async def _finalize_pick(interaction: discord.Interaction, raid_id, target_status: str, cls) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()

    display_name = interaction.user.display_name

    async with SessionLocal() as session:
        raid = await get_raid(session, raid_id)
        if raid is None or raid.cancelled:
            await interaction.edit_original_response(content="Это событие больше не активно.", view=None)
            return
        if target_status == "backup":
            await signups_service.join_as_backup(session, raid, cls, interaction.user.id, display_name)
            final_status = "backup"
        elif target_status == "maybe":
            await signups_service.set_maybe(session, raid, cls, interaction.user.id, display_name)
            final_status = "maybe"
        else:
            final_status = await signups_service.join_best_effort(
                session, raid, cls, interaction.user.id, display_name
            )
        await session.commit()

    if final_status == "accepted":
        text = f"Готово, ты в основном составе: {fmt.class_icon_text(cls)} {cls.name}."
    elif final_status == "maybe":
        text = f"Отметила тебя как \"возможно приду\": {fmt.class_icon_text(cls)} {cls.name}."
    else:
        text = (
            f"Основной состав занят, поставила тебя в запас: {fmt.class_icon_text(cls)} {cls.name}. "
            "Как только освободится место, автоматически переведу тебя и напишу."
        )
    await interaction.edit_original_response(content=text, view=None)
    _spawn_refresh(interaction.client, raid_id)
    if final_status == "backup":
        await send_faq_hint(interaction, "backup")
        await _notify_backup_position(interaction.client, raid_id, interaction.user.id)
    elif final_status == "maybe":
        await send_faq_hint(interaction, "maybe")


class SpecSelect(discord.ui.Select):
    def __init__(self, raid_id, specs, target_status: str):
        options = [
            discord.SelectOption(label=s.name[:100], value=str(s.id), emoji=fmt.class_emoji(s))
            for s in specs[:25]
        ]
        super().__init__(placeholder="Выбери спек", options=options, min_values=1, max_values=1)
        self.raid_id = raid_id
        self.specs_by_id = {str(s.id): s for s in specs}
        self.target_status = target_status

    async def callback(self, interaction: discord.Interaction) -> None:
        spec = self.specs_by_id[self.values[0]]
        await interaction.response.defer()
        await _finalize_pick(interaction, self.raid_id, self.target_status, spec)


class SpecSelectView(discord.ui.View):
    def __init__(self, raid_id, specs, target_status: str):
        super().__init__(timeout=120)
        self.add_item(SpecSelect(raid_id, specs, target_status))


class ClassSelect(discord.ui.Select):
    def __init__(self, raid_id, classes, target_status: str):
        options = [
            discord.SelectOption(label=c.name[:100], value=str(c.id), emoji=fmt.class_emoji(c))
            for c in classes[:25]
        ]
        super().__init__(placeholder="Выбери класс", options=options, min_values=1, max_values=1)
        self.raid_id = raid_id
        self.classes_by_id = {str(c.id): c for c in classes}
        self.target_status = target_status

    async def callback(self, interaction: discord.Interaction) -> None:
        cls = self.classes_by_id[self.values[0]]
        await interaction.response.defer()

        async with SessionLocal() as session:
            specs = await list_specs(session, cls.id)

        if specs:
            await interaction.edit_original_response(
                content=f"Выбери спек класса {fmt.class_icon_text(cls)} {cls.name}:",
                view=SpecSelectView(self.raid_id, specs, self.target_status),
            )
            return

        await _finalize_pick(interaction, self.raid_id, self.target_status, cls)


class ClassSelectView(discord.ui.View):
    def __init__(self, raid_id, classes, target_status: str):
        super().__init__(timeout=120)
        self.add_item(ClassSelect(raid_id, classes, target_status))


class LeaveConfirmView(discord.ui.View):
    def __init__(self, raid_id):
        super().__init__(timeout=120)
        self.raid_id = raid_id

    @discord.ui.button(label="Перезаписаться другим классом", style=discord.ButtonStyle.primary, emoji="\U0001F504")
    async def reassign(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None:
                await send_ephemeral_followup(interaction, "Событие не найдено.")
                return
            classes = await list_classes(session, raid.game_id, top_level_only=True)
        await send_ephemeral_followup(
            interaction, "Выбери новый класс:", view=ClassSelectView(self.raid_id, classes, "auto")
        )

    @discord.ui.button(label="Точно отменить запись", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await _perform_leave(interaction, self.raid_id)


async def _perform_leave(interaction: discord.Interaction, raid_id) -> None:
    async with SessionLocal() as session:
        signup = await get_signup(session, raid_id, interaction.user.id)
        if signup is None:
            await send_ephemeral_followup(interaction, "Ты и так не записан на это событие.")
            return
        promoted = await signups_service.leave_and_promote(session, raid_id, signup)
        promoted_user_id = promoted.user_id if promoted else None
        raid_title = None
        if promoted:
            raid = await get_raid(session, raid_id)
            raid_title = raid.title if raid else None
        await session.commit()

    _spawn_refresh(interaction.client, raid_id)
    await send_ephemeral_followup(interaction, "Запись отменена.")

    if promoted_user_id:
        try:
            user = await interaction.client.fetch_user(promoted_user_id)
            await user.send(
                f"Место освободилось: тебя перевели из запаса в основной состав на событии **{raid_title}**. Ты нужен там!"
            )
        except discord.HTTPException:
            pass


class SignupButton(discord.ui.Button):
    def __init__(self, raid_id, disabled: bool):
        super().__init__(
            label="Записаться",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"spark:signup:{raid_id}",
            disabled=disabled,
            row=0,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        display_name = interaction.user.display_name
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None or raid.cancelled:
                await send_ephemeral_followup(interaction, "Это событие больше не активно.")
                return
            if not fmt.is_open_now(raid):
                await send_ephemeral_followup(interaction, "Запись на это событие уже закрыта.")
                return

            existing_class = await _try_reuse_existing_class(session, raid, interaction.user.id)
            if existing_class is not None:
                final_status = await signups_service.join_best_effort(
                    session, raid, existing_class, interaction.user.id, display_name
                )
                await session.commit()

                _spawn_refresh(interaction.client, self.raid_id)
                if final_status == "accepted":
                    text = f"Готово, ты в основном составе: {fmt.class_icon_text(existing_class)} {existing_class.name}."
                else:
                    text = (
                        f"Основной состав занят, поставила тебя в запас: "
                        f"{fmt.class_icon_text(existing_class)} {existing_class.name}."
                    )
                await send_ephemeral_followup(interaction, text)
                if final_status == "backup":
                    await _notify_backup_position(interaction.client, self.raid_id, interaction.user.id)
                return

            classes = await list_classes(session, raid.game_id, top_level_only=True)

        if not classes:
            await send_ephemeral_followup(
                interaction, "У этой игры ещё нет классов, обратись к администратору."
            )
            return

        await send_ephemeral_followup(
            interaction, "Выбери класс:", view=ClassSelectView(self.raid_id, classes, "auto")
        )


class BackupButton(discord.ui.Button):
    def __init__(self, raid_id, disabled: bool):
        super().__init__(
            label="Запасной",
            emoji="\U0001F551",
            style=discord.ButtonStyle.secondary,
            custom_id=f"spark:backup:{raid_id}",
            disabled=disabled,
            row=0,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        display_name = interaction.user.display_name
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None or raid.cancelled:
                await send_ephemeral_followup(interaction, "Это событие больше не активно.")
                return
            if not fmt.is_open_now(raid):
                await send_ephemeral_followup(interaction, "Запись на это событие уже закрыта.")
                return

            existing_class = await _try_reuse_existing_class(session, raid, interaction.user.id)
            if existing_class is not None:
                await signups_service.join_as_backup(
                    session, raid, existing_class, interaction.user.id, display_name
                )
                await session.commit()

                _spawn_refresh(interaction.client, self.raid_id)
                text = f"Поставила тебя в запас: {fmt.class_icon_text(existing_class)} {existing_class.name}."
                await send_ephemeral_followup(interaction, text)
                await send_faq_hint(interaction, "backup")
                await _notify_backup_position(interaction.client, self.raid_id, interaction.user.id)
                return

            classes = await list_classes(session, raid.game_id, top_level_only=True)

        if not classes:
            await send_ephemeral_followup(
                interaction, "У этой игры ещё нет классов, обратись к администратору."
            )
            return

        await send_ephemeral_followup(
            interaction, "Выбери класс для запаса:", view=ClassSelectView(self.raid_id, classes, "backup")
        )


class MaybeButton(discord.ui.Button):
    def __init__(self, raid_id, disabled: bool):
        super().__init__(
            label="Возможно",
            emoji="❔",
            style=discord.ButtonStyle.secondary,
            custom_id=f"spark:maybe:{raid_id}",
            disabled=disabled,
            row=0,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        display_name = interaction.user.display_name
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None or raid.cancelled:
                await send_ephemeral_followup(interaction, "Это событие больше не активно.")
                return

            existing_class = await _try_reuse_existing_class(session, raid, interaction.user.id)
            if existing_class is not None:
                await signups_service.set_maybe(session, raid, existing_class, interaction.user.id, display_name)
                await session.commit()

                _spawn_refresh(interaction.client, self.raid_id)
                text = (
                    f"Отметила тебя как \"возможно приду\": "
                    f"{fmt.class_icon_text(existing_class)} {existing_class.name}."
                )
                await send_ephemeral_followup(interaction, text)
                await send_faq_hint(interaction, "maybe")
                return

            classes = await list_classes(session, raid.game_id, top_level_only=True)
            if not classes:
                await signups_service.set_maybe(session, raid, None, interaction.user.id, display_name)
                await session.commit()

                _spawn_refresh(interaction.client, self.raid_id)
                await send_ephemeral_followup(interaction, "Отметила тебя как \"возможно приду\".")
                await send_faq_hint(interaction, "maybe")
                return

        await send_ephemeral_followup(
            interaction, "Выбери класс:", view=ClassSelectView(self.raid_id, classes, "maybe")
        )


class DeclineButton(discord.ui.Button):
    def __init__(self, raid_id):
        super().__init__(
            label="Не приду",
            emoji="❌",
            style=discord.ButtonStyle.secondary,
            custom_id=f"spark:decline:{raid_id}",
            row=0,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None:
                await send_ephemeral_followup(interaction, "Событие не найдено.")
                return
            await signups_service.set_declined(session, raid, interaction.user.id, interaction.user.display_name)
            await session.commit()

        _spawn_refresh(interaction.client, self.raid_id)
        await send_ephemeral_followup(interaction, "Отметила тебя как \"точно не приду\".")
        await send_faq_hint(interaction, "decline")


class LeaveButton(discord.ui.Button):
    def __init__(self, raid_id):
        super().__init__(
            label="Отменить запись",
            emoji="\U0001F6AA",
            style=discord.ButtonStyle.danger,
            custom_id=f"spark:leave:{raid_id}",
            row=0,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with SessionLocal() as session:
            signup = await get_signup(session, self.raid_id, interaction.user.id)

        if signup is None:
            await send_ephemeral_followup(interaction, "Ты и так не записан на это событие.")
            return

        if signup.status in ("accepted", "backup") and signup.class_id:
            await send_ephemeral_followup(
                interaction,
                "Хочешь перезаписаться другим классом или отменить запись совсем?",
                view=LeaveConfirmView(self.raid_id),
            )
            return

        await _perform_leave(interaction, self.raid_id)


class NotificationButton(discord.ui.Button):
    def __init__(self, raid_id):
        super().__init__(
            label="Уведомления",
            emoji="\U0001F514",
            style=discord.ButtonStyle.secondary,
            custom_id=f"spark:notify:{raid_id}",
            row=1,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with SessionLocal() as session:
            signup = await get_signup(session, self.raid_id, interaction.user.id)
            if signup is None:
                await send_ephemeral_followup(
                    interaction, "Сначала запишись на событие, чтобы настраивать напоминания."
                )
                return
            enabled = await signups_service.toggle_notifications(session, signup)
            await session.commit()

        state = "включены" if enabled else "выключены"
        await send_ephemeral_followup(interaction, f"Личные напоминания по этому событию {state}.")
        await send_faq_hint(interaction, "notifications")


class HelpButton(discord.ui.Button):
    def __init__(self, raid_id):
        super().__init__(
            label="Помощь",
            emoji="❓",
            style=discord.ButtonStyle.secondary,
            custom_id=f"spark:help:{raid_id}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await send_faq_hub(interaction)


class MyEventsButton(discord.ui.Button):
    def __init__(self, raid_id):
        super().__init__(
            label="Мои события",
            emoji="\U0001F4CB",
            style=discord.ButtonStyle.secondary,
            custom_id=f"spark:myevents:{raid_id}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        from app.bot.views.event_admin import send_my_events

        await send_my_events(interaction)


class ShowRosterButton(discord.ui.Button):
    def __init__(self, raid_id):
        super().__init__(
            label="Показать участников",
            emoji="\U0001F465",
            style=discord.ButtonStyle.secondary,
            custom_id=f"spark:roster:{raid_id}",
            row=1,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with SessionLocal() as session:
            raid = await get_raid(session, self.raid_id)
            if raid is None:
                await send_ephemeral_followup(interaction, "Событие не найдено.")
                return
            classes = await list_classes(session, raid.game_id, active_only=False)
            embed = build_roster_breakdown_embed(raid, classes)

        await send_ephemeral_followup(interaction, embed=embed)


class RefreshButton(discord.ui.Button):
    def __init__(self, raid_id):
        super().__init__(
            label="Обновить",
            emoji="\U0001F504",
            style=discord.ButtonStyle.secondary,
            custom_id=f"spark:refresh:{raid_id}",
            row=1,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await is_spark_admin(interaction):
            await interaction.response.send_message(
                "Обновлять карточку могут только администраторы.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await refresh_raid_message(interaction.client, self.raid_id)
        await send_ephemeral_followup(interaction, "Карточка обновлена.")


def build_signup_view(raid_id, classes, disabled: bool = False) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(SignupButton(raid_id, disabled))
    view.add_item(BackupButton(raid_id, disabled))
    view.add_item(MaybeButton(raid_id, disabled))
    view.add_item(DeclineButton(raid_id))
    view.add_item(LeaveButton(raid_id))
    view.add_item(NotificationButton(raid_id))
    view.add_item(HelpButton(raid_id))
    view.add_item(MyEventsButton(raid_id))
    view.add_item(ShowRosterButton(raid_id))
    view.add_item(RefreshButton(raid_id))
    return view
