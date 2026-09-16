from datetime import datetime
from typing import Awaitable, Callable

import discord

from app.bot.state import EventDraft
from app.utils.time import parse_local_datetime

PAST_DATE_ERROR = (
    "Это время уже в прошлом по МСК. Укажи дату и время в будущем, в московском времени."
)


def _truncate_utf16(value: str, limit: int) -> str:
    encoded = value.encode("utf-16-le")
    if len(encoded) <= limit * 2:
        return value
    truncated = encoded[: limit * 2]
    try:
        return truncated.decode("utf-16-le")
    except UnicodeDecodeError:
        return truncated[:-2].decode("utf-16-le")


class EventBasicsModal(discord.ui.Modal):
    def __init__(
        self,
        draft: EventDraft,
        on_submit_next: Callable[[discord.Interaction, EventDraft], Awaitable[None]],
        tz_name: str | None = None,
        default_datetime: str = "",
    ):
        super().__init__(title="Событие: основное")
        self.draft = draft
        self.on_submit_next = on_submit_next
        self.tz_name = tz_name

        self.title_input = discord.ui.TextInput(
            label="Название", max_length=200, default=_truncate_utf16(draft.title or "", 200)
        )
        self.description_input = discord.ui.TextInput(
            label="Описание",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1500,
            default=_truncate_utf16(draft.description or "", 1500),
        )
        self.datetime_input = discord.ui.TextInput(
            label="Дата и время, МСК (ГГГГ-ММ-ДД ЧЧ:ММ)",
            placeholder="2026-09-20 19:00",
            default=_truncate_utf16(default_datetime, 16),
            max_length=16,
        )
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.datetime_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            starts_at = parse_local_datetime(self.datetime_input.value, self.tz_name)
        except ValueError:
            await interaction.response.send_message(
                "Не получилось распознать дату. Формат: ГГГГ-ММ-ДД ЧЧ:ММ, например 2026-09-20 19:00.",
                ephemeral=True,
            )
            return
        if starts_at <= datetime.utcnow():
            await interaction.response.send_message(PAST_DATE_ERROR, ephemeral=True)
            return
        self.draft.title = self.title_input.value.strip()
        self.draft.description = self.description_input.value.strip() or None
        self.draft.starts_at = starts_at
        await self.on_submit_next(interaction, self.draft)


class EventParamsModal(discord.ui.Modal):
    def __init__(
        self,
        draft: EventDraft,
        on_submit_next: Callable[[discord.Interaction, EventDraft], Awaitable[None]],
    ):
        super().__init__(title="Событие: параметры")
        self.draft = draft
        self.on_submit_next = on_submit_next

        self.limit_input = discord.ui.TextInput(
            label="Лимит состава (0 = без лимита)",
            default=str(draft.participant_limit),
            max_length=4,
        )
        self.reminder_input = discord.ui.TextInput(
            label="Напомнить за N минут до старта",
            default=str(draft.reminder_minutes),
            max_length=5,
        )
        self.duration_input = discord.ui.TextInput(
            label="Длительность в минутах",
            default=str(draft.duration_minutes),
            max_length=5,
            required=False,
        )
        self.add_item(self.limit_input)
        self.add_item(self.reminder_input)
        self.add_item(self.duration_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            limit = int(self.limit_input.value)
            reminder = int(self.reminder_input.value)
            duration = (
                int(self.duration_input.value) if self.duration_input.value.strip() else self.draft.duration_minutes
            )
            if limit < 0 or reminder < 0 or duration <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Лимит, напоминание и длительность - это целые числа (0 разрешён только для лимита).",
                ephemeral=True,
            )
            return
        self.draft.participant_limit = limit
        self.draft.reminder_minutes = reminder
        self.draft.duration_minutes = duration
        await self.on_submit_next(interaction, self.draft)


class GameCreateModal(discord.ui.Modal):
    def __init__(self, on_submit_next: Callable[[discord.Interaction, str, str], Awaitable[None]]):
        super().__init__(title="Новая игра")
        self.on_submit_next = on_submit_next
        self.name_input = discord.ui.TextInput(label="Название игры", max_length=100)
        self.icon_input = discord.ui.TextInput(
            label="Эмодзи-иконка", required=False, max_length=10, placeholder="\U0001F3AE"
        )
        self.add_item(self.name_input)
        self.add_item(self.icon_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        icon = (self.icon_input.value or "").strip() or "\U0001F3AE"
        await self.on_submit_next(interaction, self.name_input.value.strip(), icon)


class GameColorModal(discord.ui.Modal):
    def __init__(self, current_color: int, on_submit_next: Callable[[discord.Interaction, int], Awaitable[None]]):
        super().__init__(title="Цвет игры")
        self.on_submit_next = on_submit_next
        self.color_input = discord.ui.TextInput(
            label="Цвет в HEX (например 000000 - чёрный)",
            default=f"{current_color:06X}",
            max_length=7,
            placeholder="000000",
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        value = self.color_input.value.strip().lstrip("#")
        try:
            color = int(value, 16)
            if not (0 <= color <= 0xFFFFFF):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Не получилось распознать цвет. Формат: HEX, например 000000 или FF5500.",
                ephemeral=True,
            )
            return
        await self.on_submit_next(interaction, color)


class ClassCreateModal(discord.ui.Modal):
    def __init__(
        self,
        on_submit_next: Callable[[discord.Interaction, str, int], Awaitable[None]],
        title: str = "Новый класс",
    ):
        super().__init__(title=title)
        self.on_submit_next = on_submit_next
        self.name_input = discord.ui.TextInput(label="Название", max_length=100)
        self.limit_input = discord.ui.TextInput(
            label="Лимит слотов (0 = без лимита)", default="0", max_length=4
        )
        self.add_item(self.name_input)
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            limit = int(self.limit_input.value)
            if limit < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Лимит - это целое число 0 или больше.", ephemeral=True
            )
            return
        await self.on_submit_next(interaction, self.name_input.value.strip(), limit)


class TemplateBasicsModal(discord.ui.Modal):
    def __init__(
        self,
        draft: EventDraft,
        on_submit_next: Callable[[discord.Interaction, EventDraft], Awaitable[None]],
    ):
        super().__init__(title="Шаблон: основное")
        self.draft = draft
        self.on_submit_next = on_submit_next

        self.name_input = discord.ui.TextInput(
            label="Название шаблона (для списка)", max_length=150, default=_truncate_utf16(draft.name or "", 150)
        )
        self.title_input = discord.ui.TextInput(
            label="Название события", max_length=200, default=_truncate_utf16(draft.title or "", 200)
        )
        self.description_input = discord.ui.TextInput(
            label="Описание",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1500,
            default=_truncate_utf16(draft.description or "", 1500),
        )
        self.add_item(self.name_input)
        self.add_item(self.title_input)
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.draft.name = self.name_input.value.strip()
        self.draft.title = self.title_input.value.strip()
        self.draft.description = self.description_input.value.strip() or None
        await self.on_submit_next(interaction, self.draft)


class RecurrenceTimeModal(discord.ui.Modal):
    def __init__(
        self,
        on_submit_next: Callable[[discord.Interaction, str, int], Awaitable[None]],
        default_time: str = "19:00",
        default_lead_days: int = 3,
    ):
        super().__init__(title="Время повтора")
        self.on_submit_next = on_submit_next
        self.time_input = discord.ui.TextInput(label="Время (ЧЧ:ММ)", default=default_time, max_length=5, placeholder="19:00")
        self.lead_input = discord.ui.TextInput(
            label="За сколько дней публиковать", default=str(default_lead_days), max_length=2
        )
        self.add_item(self.time_input)
        self.add_item(self.lead_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        value = self.time_input.value.strip()
        try:
            hour, minute = (int(part) for part in value.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
            lead_days = int(self.lead_input.value)
            if lead_days <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Время в формате ЧЧ:ММ, дни - целое число больше 0.", ephemeral=True
            )
            return
        await self.on_submit_next(interaction, value, lead_days)


class TemplateNameModal(discord.ui.Modal):
    def __init__(self, on_submit_next: Callable[[discord.Interaction, str], Awaitable[None]]):
        super().__init__(title="Название шаблона")
        self.on_submit_next = on_submit_next
        self.name_input = discord.ui.TextInput(label="Название шаблона", max_length=150)
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.on_submit_next(interaction, self.name_input.value.strip())


class RescheduleModal(discord.ui.Modal):
    def __init__(
        self,
        current_value: str,
        on_submit_next: Callable[[discord.Interaction, "object"], Awaitable[None]],
        tz_name: str | None = None,
    ):
        super().__init__(title="Новая дата и время")
        self.on_submit_next = on_submit_next
        self.tz_name = tz_name
        self.datetime_input = discord.ui.TextInput(
            label="Дата и время, МСК (ГГГГ-ММ-ДД ЧЧ:ММ)",
            default=current_value,
            placeholder="2026-09-20 19:00",
            max_length=16,
        )
        self.add_item(self.datetime_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            starts_at = parse_local_datetime(self.datetime_input.value, self.tz_name)
        except ValueError:
            await interaction.response.send_message(
                "Не получилось распознать дату. Формат: ГГГГ-ММ-ДД ЧЧ:ММ.",
                ephemeral=True,
            )
            return
        if starts_at <= datetime.utcnow():
            await interaction.response.send_message(PAST_DATE_ERROR, ephemeral=True)
            return
        await self.on_submit_next(interaction, starts_at)


class NotifyNowModal(discord.ui.Modal):
    def __init__(self, on_submit_next: Callable[[discord.Interaction, str | None], Awaitable[None]]):
        super().__init__(title="Срочное уведомление")
        self.on_submit_next = on_submit_next
        self.text_input = discord.ui.TextInput(
            label="Текст сообщения",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
            placeholder="Если оставить пустым - уйдёт стандартный текст напоминания.",
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.on_submit_next(interaction, self.text_input.value.strip() or None)
