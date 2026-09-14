import asyncio
import logging
import uuid

import discord

from app.config import settings
from app.database.session import SessionLocal
from app.repositories import raids as raid_repo
from app.repositories.classes import get_class, delete_class_by_id
from app.repositories.raids import is_registration_open, event_main_is_full
from app.services.raids import refresh_raid_message
from app.bot.ephemeral import send_ephemeral_followup
from app.repositories import admin_roles as admin_role_repo

EPHEMERAL_DELETE_AFTER = settings.ephemeral_delete_after
log = logging.getLogger("SP4RK.ui")


def _safe_select_emoji(icon: str):
    if not icon:
        return None
    if icon.startswith(":") and icon.endswith(":"):
        return None
    return icon


async def delete_ephemeral_later(interaction: discord.Interaction, delay: int = EPHEMERAL_DELETE_AFTER) -> None:
    await asyncio.sleep(delay)
    try:
        await interaction.delete_original_response()
    except Exception:
        pass


async def _closed_reply(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🔒 Регистрация уже закрыта. SP4RK закрывает запись за 1 минуту до начала события.",
        ephemeral=True,
        delete_after=EPHEMERAL_DELETE_AFTER,
    )


class ClassSignupSelect(discord.ui.Select):
    def __init__(self, raid_id: uuid.UUID, raid_classes, status: str):
        self.raid_id = raid_id
        self.status = status

        if status == "accepted":
            placeholder = "Выберите класс для записи"
            status_label = "Записаться"
        else:
            placeholder = "Выберите класс для записи в запас"
            status_label = "Запасной"

        options: list[discord.SelectOption] = []
        for cls in raid_classes[:25]:
            options.append(
                discord.SelectOption(
                    label=cls.name[:100],
                    value=str(cls.id),
                    description=f"{status_label} • лимит: {cls.limit_count or 'без лимита'}",
                    emoji=_safe_select_emoji(cls.icon),
                )
            )

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"sp4rk_class_pick:{status}:{raid_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            await self._callback_impl(interaction)
        except Exception as exc:
            log.exception("Class signup select failed: %s", type(exc).__name__)
            try:
                if interaction.response.is_done():
                    await send_ephemeral_followup(interaction, "❌ Не удалось обработать выбор класса. Попробуйте ещё раз.")
                else:
                    await interaction.response.send_message("❌ Не удалось обработать выбор класса. Попробуйте ещё раз.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
            except Exception:
                pass

    async def _callback_impl(self, interaction: discord.Interaction):
        class_id = uuid.UUID(self.values[0])

        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, self.raid_id)
            if not raid or raid.cancelled or raid.archived:
                await interaction.response.edit_message(content="❌ Событие не найдено или уже закрыто.", embed=None, view=None)
                asyncio.create_task(delete_ephemeral_later(interaction))
                return
            if not is_registration_open(raid):
                await interaction.response.edit_message(content="🔒 Регистрация уже закрыта.", embed=None, view=None)
                asyncio.create_task(delete_ephemeral_later(interaction))
                await refresh_raid_message(interaction.client, self.raid_id)
                return

            raid_class = await get_class(session, class_id)
            if not raid_class or not raid_class.is_active:
                await interaction.response.edit_message(content="❌ Этот класс больше недоступен.", embed=None, view=None)
                asyncio.create_task(delete_ephemeral_later(interaction))
                return

            from app.repositories.classes import list_classes
            fresh_classes = await list_classes(session, raid.guild_id)

            if self.status == "accepted":
                if event_main_is_full(raid, interaction.user.id):
                    await interaction.response.edit_message(
                        content=(
                            "🪑 Основной состав события уже заполнен.\n"
                            "SP4RK может записать вас на скамейку запасных — выберите класс ниже."
                        ),
                        embed=None,
                        view=ClassPickView(self.raid_id, fresh_classes, "backup"),
                    )
                    return

                current_count = sum(
                    1 for signup in raid.signups
                    if signup.status == "accepted"
                    and signup.class_id == class_id
                    and signup.user_id != interaction.user.id
                )
                if raid_class.limit_count and current_count >= raid_class.limit_count:
                    await interaction.response.edit_message(
                        content=(
                            f"❌ Места для {raid_class.icon} **{raid_class.name}** уже закончились.\n"
                            "Можно выбрать другой класс или записаться в запас."
                        ),
                        embed=None,
                        view=ClassLimitChoiceView(self.raid_id, fresh_classes),
                    )
                    return

            await raid_repo.upsert_signup(
                session=session,
                raid_id=self.raid_id,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
                class_id=class_id,
                status=self.status,
            )
            await session.commit()

        await refresh_raid_message(interaction.client, self.raid_id)

        if self.status == "accepted":
            text = f"✅ Вы записались как {raid_class.icon} **{raid_class.name}**."
        else:
            text = f"🪑 Вы записаны в запас как {raid_class.icon} **{raid_class.name}**."

        await interaction.response.edit_message(content=text, embed=None, view=None)
        asyncio.create_task(delete_ephemeral_later(interaction))


class ClassPickView(discord.ui.View):
    def __init__(self, raid_id: uuid.UUID, raid_classes, status: str):
        super().__init__(timeout=120)
        self.add_item(ClassSignupSelect(raid_id, raid_classes, status))


class ClassLimitChoiceView(discord.ui.View):
    def __init__(self, raid_id: uuid.UUID, raid_classes):
        super().__init__(timeout=120)
        self.add_item(ClassSignupSelect(raid_id, raid_classes, "accepted"))
        self.add_item(ClassSignupSelect(raid_id, raid_classes, "backup"))


class SignupButton(discord.ui.Button):
    def __init__(self, raid_id: uuid.UUID, disabled: bool = False):
        super().__init__(
            label="Записаться",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"sp4rk_signup_open:{raid_id}",
            disabled=disabled,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, self.raid_id)
            if not raid or raid.cancelled or raid.archived:
                return await interaction.response.send_message("❌ Событие не найдено или уже закрыто.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
            if not is_registration_open(raid):
                return await _closed_reply(interaction)
            from app.repositories.classes import list_classes
            raid_classes = await list_classes(session, interaction.guild.id)

        if not raid_classes:
            return await interaction.response.send_message("❌ Для этого сервера пока не настроены классы.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

        await interaction.response.send_message(
            "Выберите класс для записи:",
            view=ClassPickView(self.raid_id, raid_classes, "accepted"),
            ephemeral=True,
            delete_after=EPHEMERAL_DELETE_AFTER,
        )


class BackupButton(discord.ui.Button):
    def __init__(self, raid_id: uuid.UUID, disabled: bool = False):
        super().__init__(
            label="Запасной",
            emoji="🪑",
            style=discord.ButtonStyle.secondary,
            custom_id=f"sp4rk_backup_open:{raid_id}",
            disabled=disabled,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, self.raid_id)
            if not raid or raid.cancelled or raid.archived:
                return await interaction.response.send_message("❌ Событие не найдено или уже закрыто.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
            if not is_registration_open(raid):
                return await _closed_reply(interaction)
            from app.repositories.classes import list_classes
            raid_classes = await list_classes(session, interaction.guild.id)

        if not raid_classes:
            return await interaction.response.send_message("❌ Для этого сервера пока не настроены классы.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

        await interaction.response.send_message(
            "Выберите класс для записи в запас:",
            view=ClassPickView(self.raid_id, raid_classes, "backup"),
            ephemeral=True,
            delete_after=EPHEMERAL_DELETE_AFTER,
        )


class MaybeButton(discord.ui.Button):
    def __init__(self, raid_id: uuid.UUID, disabled: bool = False):
        super().__init__(
            label="Возможно буду",
            emoji="❔",
            style=discord.ButtonStyle.primary,
            custom_id=f"sp4rk_maybe:{raid_id}",
            disabled=disabled,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, self.raid_id)
            if not raid or raid.cancelled or raid.archived:
                return await interaction.response.send_message("❌ Событие не найдено или уже закрыто.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
            if not is_registration_open(raid):
                return await _closed_reply(interaction)
            await raid_repo.upsert_signup(session, self.raid_id, interaction.user.id, interaction.user.display_name, None, "maybe")
            await session.commit()

        await refresh_raid_message(interaction.client, self.raid_id)
        await interaction.response.send_message("❔ Вы отмечены как **возможно будете**.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)


class DeclineButton(discord.ui.Button):
    def __init__(self, raid_id: uuid.UUID, disabled: bool = False):
        super().__init__(
            label="Точно не буду",
            emoji="❌",
            style=discord.ButtonStyle.secondary,
            custom_id=f"sp4rk_decline:{raid_id}",
            disabled=disabled,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, self.raid_id)
            if not raid or raid.cancelled or raid.archived:
                return await interaction.response.send_message("❌ Событие не найдено или уже закрыто.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
            if not is_registration_open(raid):
                return await _closed_reply(interaction)
            await raid_repo.upsert_signup(session, self.raid_id, interaction.user.id, interaction.user.display_name, None, "declined")
            await session.commit()

        await refresh_raid_message(interaction.client, self.raid_id)
        await interaction.response.send_message("❌ Вы отмечены как **точно не будете**.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)


class LeaveButton(discord.ui.Button):
    def __init__(self, raid_id: uuid.UUID, disabled: bool = False):
        super().__init__(
            label="Отменить запись",
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            custom_id=f"sp4rk_leave:{raid_id}",
            disabled=disabled,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, self.raid_id)
            if not raid or raid.cancelled or raid.archived:
                return await interaction.response.send_message("❌ Событие не найдено или уже закрыто.", ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)
            if not is_registration_open(raid):
                return await _closed_reply(interaction)
            ok = await raid_repo.delete_signup(session, self.raid_id, interaction.user.id)
            await session.commit()

        await refresh_raid_message(interaction.client, self.raid_id)
        text = "✖️ Ваша запись отменена." if ok else "Вы не были записаны на это событие."
        await interaction.response.send_message(text, ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)


class NotificationButton(discord.ui.Button):
    def __init__(self, raid_id: uuid.UUID, disabled: bool = False):
        super().__init__(
            label="ЛС-уведомление",
            emoji="🔔",
            style=discord.ButtonStyle.secondary,
            custom_id=f"sp4rk_notify_toggle:{raid_id}",
            disabled=disabled,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, self.raid_id)
            if not raid or raid.cancelled or raid.archived:
                return await interaction.response.send_message(
                    "❌ Событие не найдено или уже закрыто.",
                    ephemeral=True,
                    delete_after=EPHEMERAL_DELETE_AFTER,
                )
            signup = await raid_repo.toggle_notifications(session, self.raid_id, interaction.user.id)
            await session.commit()

        if not signup:
            return await interaction.response.send_message(
                "Сначала выберите статус участия в этом событии. После этого можно включить или отключить ЛС-напоминание.",
                ephemeral=True,
                delete_after=EPHEMERAL_DELETE_AFTER,
            )

        if signup.notifications_enabled:
            text = "🔔 ЛС-напоминание по этому событию включено."
        else:
            text = "🔕 ЛС-напоминание по этому событию отключено."

        await interaction.response.send_message(text, ephemeral=True, delete_after=EPHEMERAL_DELETE_AFTER)

async def _is_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False

    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    if not member:
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except Exception:
            pass

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


class UserKickSelect(discord.ui.Select):
    def __init__(self, raid_id: uuid.UUID, signups_chunk):
        self.raid_id = raid_id
        options = []
        
        status_map = {"accepted": "Основной", "backup": "Запас", "maybe": "Возможно", "declined": "Отказ"}
        for s in signups_chunk:
            name = str(getattr(s, "display_name", "") or f"ID {s.user_id}")[:50]
            status_str = status_map.get(s.status, s.status)
            options.append(
                discord.SelectOption(
                    label=name,
                    value=str(s.user_id),
                    description=f"Статус: {status_str}",
                    emoji="👤",
                )
            )
        
        super().__init__(placeholder="Выберите участника для удаления", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        user_id_to_kick = int(self.values[0])
        async with SessionLocal() as session:
            ok = await raid_repo.delete_signup(session, self.raid_id, user_id_to_kick)
            await session.commit()
        
        if not ok:
            await interaction.response.edit_message(content="❌ Участник не найден или уже удалён.", view=None)
            asyncio.create_task(delete_ephemeral_later(interaction))
            return

        await refresh_raid_message(interaction.client, self.raid_id)
        await interaction.response.edit_message(content="✅ Участник успешно удалён из события.", view=None)
        asyncio.create_task(delete_ephemeral_later(interaction))


class AdminKickPickView(discord.ui.View):
    def __init__(self, raid_id: uuid.UUID, signups, page: int = 0):
        super().__init__(timeout=120)
        self.raid_id = raid_id
        self.signups = signups
        self.page = page
        
        start = self.page * 25
        end = start + 25
        chunk = self.signups[start:end]
        
        self.add_item(UserKickSelect(self.raid_id, chunk))
        
        if len(self.signups) > 25:
            prev_btn = discord.ui.Button(
                label="⬅️ Назад", 
                style=discord.ButtonStyle.secondary, 
                disabled=(self.page == 0)
            )
            next_btn = discord.ui.Button(
                label="Вперед ➡️", 
                style=discord.ButtonStyle.secondary, 
                disabled=(end >= len(self.signups))
            )
            
            async def prev_callback(interaction: discord.Interaction):
                await interaction.response.edit_message(
                    view=AdminKickPickView(self.raid_id, self.signups, self.page - 1)
                )

            async def next_callback(interaction: discord.Interaction):
                await interaction.response.edit_message(
                    view=AdminKickPickView(self.raid_id, self.signups, self.page + 1)
                )

            prev_btn.callback = prev_callback
            next_btn.callback = next_callback
            
            self.add_item(prev_btn)
            self.add_item(next_btn)

class AdminKickButton(discord.ui.Button):
    def __init__(self, raid_id: uuid.UUID, disabled: bool = False):
        super().__init__(
            label="Удалить участника",
            emoji="🛠️",
            style=discord.ButtonStyle.danger,
            custom_id=f"sp4rk_admin_kick:{raid_id}",
            disabled=disabled,
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        if not await _is_admin(interaction):
            return await interaction.response.send_message(
                "❌ У тебя нет прав для администрирования SP4RK. Эта кнопка только для администраторов.", 
                ephemeral=True, 
                delete_after=EPHEMERAL_DELETE_AFTER
            )

        async with SessionLocal() as session:
            raid = await raid_repo.get_raid(session, self.raid_id)
            if not raid or raid.cancelled or raid.archived:
                return await interaction.response.send_message(
                    "❌ Событие не найдено или уже закрыто.", 
                    ephemeral=True, 
                    delete_after=EPHEMERAL_DELETE_AFTER
                )
            
            signups = raid.signups
            if not signups:
                return await interaction.response.send_message(
                    "❌ В событии пока нет записанных участников.", 
                    ephemeral=True, 
                    delete_after=EPHEMERAL_DELETE_AFTER
                )

        await interaction.response.send_message(
            "Выберите участника, которого нужно вычеркнуть:",
            view=AdminKickPickView(self.raid_id, signups),
            ephemeral=True,
            delete_after=EPHEMERAL_DELETE_AFTER,
        )

class SignupView(discord.ui.View):
    def __init__(self, raid_id: uuid.UUID, raid_classes=None, disabled: bool = False):
        super().__init__(timeout=None)
        self.add_item(SignupButton(raid_id, disabled=disabled))
        self.add_item(LeaveButton(raid_id, disabled=disabled))
        self.add_item(MaybeButton(raid_id, disabled=disabled))
        self.add_item(BackupButton(raid_id, disabled=disabled))
        self.add_item(DeclineButton(raid_id, disabled=disabled))
        self.add_item(NotificationButton(raid_id, disabled=disabled))
        self.add_item(AdminKickButton(raid_id, disabled=disabled))

def build_signup_view(raid_id: uuid.UUID, raid_classes=None, disabled: bool = False) -> SignupView:
    return SignupView(raid_id, raid_classes, disabled=disabled)


class DeleteClassSelect(discord.ui.Select):
    def __init__(self, raid_classes):
        options = [
            discord.SelectOption(
                label=c.name[:100],
                value=str(c.id),
                description=f"Лимит: {c.limit_count or 'без лимита'}",
                emoji=_safe_select_emoji(c.icon),
            )
            for c in raid_classes[:25]
        ]
        super().__init__(placeholder="Выберите класс, который нужно удалить", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        class_id = uuid.UUID(self.values[0])
        async with SessionLocal() as session:
            cls = await delete_class_by_id(session, interaction.guild.id, class_id)
            await session.commit()
        if not cls:
            await interaction.response.edit_message(content="❌ Класс не найден.", embed=None, view=None)
            asyncio.create_task(delete_ephemeral_later(interaction))
            return
        await interaction.response.edit_message(content=f"🗑️ Класс **{cls.name}** удалён.", embed=None, view=None)
        asyncio.create_task(delete_ephemeral_later(interaction))


class DeleteClassView(discord.ui.View):
    def __init__(self, raid_classes):
        super().__init__(timeout=120)
        self.add_item(DeleteClassSelect(raid_classes))
