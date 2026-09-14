import uuid
from collections import defaultdict

import discord

from app.database.session import SessionLocal
from app.repositories import classes as class_repo
from app.repositories import raids as raid_repo
from app.repositories.raids import is_registration_open, utcnow
from app.utils.time import discord_ts, short_id

BRAND_COLOR = 0x7C5CFF
CLOSED_COLOR = 0x2F3136
WARNING_COLOR = 0xF5C451


def _safe_display_name(signup) -> str:
    name = str(getattr(signup, "display_name", "") or f"ID {signup.user_id}").replace("\n", " ").strip()
    name = discord.utils.escape_mentions(discord.utils.escape_markdown(name))
    if len(name) > 80:
        name = name[:77].rstrip() + "..."
    return name or f"ID {signup.user_id}"


def _sorted_signups(signups):
    return sorted(signups, key=lambda s: (getattr(s, "joined_at", None) is None, getattr(s, "joined_at", None), str(s.user_id)))


def _participant_link(signup, number: int) -> str:
    # Не используем сырой <@id> в карточке: часть клиентов Discord иногда показывает его цифрами.
    # Вместо этого делаем кликабельный компактный номер профиля + сохранённый никнейм участника.
    return f"[[{number}](https://discord.com/users/{signup.user_id})] {_safe_display_name(signup)}"


def _numbered_participants(signups) -> str:
    items = _sorted_signups(signups)
    if not items:
        return "—"
    return "\n".join(_participant_link(signup, idx) for idx, signup in enumerate(items, start=1))


def _compact_participants(signups) -> str:
    items = _sorted_signups(signups)
    if not items:
        return "—"
    return ", ".join(_participant_link(signup, idx) for idx, signup in enumerate(items, start=1))


def _limit_text(limit_count: int | None) -> str:
    return "∞" if not limit_count else str(limit_count)


def _minutes_phrase(minutes: int) -> str:
    if 11 <= minutes % 100 <= 14:
        word = "минут"
    elif minutes % 10 == 1:
        word = "минуту"
    elif 2 <= minutes % 10 <= 4:
        word = "минуты"
    else:
        word = "минут"
    return f"{minutes} {word}"


def _status_text(raid, open_now: bool) -> tuple[str, int]:
    if raid.cancelled:
        return "🗑️  Событие отменено.", CLOSED_COLOR
    if raid.archived or raid.starts_at <= utcnow():
        return "🏁 Событие завершено.", CLOSED_COLOR
    if not open_now:
        return "🔒 Регистрация закрыта.", WARNING_COLOR
    return "🟢 Регистрация открыта.", BRAND_COLOR


def _safe_embed_title(title: str) -> tuple[str, str | None]:
    title = (title or "Событие").strip()
    if len(title) <= 240:
        return title, None
    return "SP4RK • Событие", title


def build_raid_embed(raid, raid_classes) -> discord.Embed:
    open_now = is_registration_open(raid)
    state, color = _status_text(raid, open_now)

    embed_title, long_title = _safe_embed_title(raid.title)
    description_lines: list[str] = []

    if long_title:
        description_lines.append(long_title)
        description_lines.append("")

    if raid.description:
        description_lines.append(raid.description.strip())
        description_lines.append("")

    description_lines.extend(
        [
            f"🕒 **Начало:** {discord_ts(raid.starts_at, 'F')}.",
            f"⏳ **Начнётся:** {discord_ts(raid.starts_at, 'R')}.",
            "🔒 **Запись закрывается:** за **1 минуту** до начала.",
            f"🔔 **ЛС-напоминание:** за **{_minutes_phrase(raid.reminder_minutes)}** до начала.",
            f"🆔 **ID:** `{short_id(raid.id)}`.",
        ]
    )

    embed = discord.Embed(
        title=embed_title,
        description="\n".join(description_lines),
        color=color,
    )

    accepted_total = sum(1 for s in raid.signups if s.status == "accepted")
    participant_limit = getattr(raid, "participant_limit", 0) or 0
    accepted_limit_text = f"{accepted_total}/{participant_limit}" if participant_limit else str(accepted_total)
    backup_total = sum(1 for s in raid.signups if s.status == "backup")
    maybe_total = sum(1 for s in raid.signups if s.status == "maybe")
    declined_total = sum(1 for s in raid.signups if s.status == "declined")

    embed.add_field(
        name="**СТАТУС СОБЫТИЯ**",
        value=(
            f"{state}\n"
            f"✅ Основной состав: **{accepted_limit_text}**.\n"
            f"🪑 Запас: **{backup_total}**.\n"
            f"❔ Возможно будут: **{maybe_total}**.\n"
            f"❌ Точно не будут: **{declined_total}**."
        ),
        inline=False,
    )

    accepted_classes = []
    for cls in raid_classes:
        members = [
            s for s in raid.signups
            if s.status == "accepted" and s.class_id == cls.id
        ]
        if not members:
            continue
        limit = _limit_text(cls.limit_count)
        accepted_classes.append((cls, members, limit))

    if accepted_classes:
        embed.add_field(
            name="**СОСТАВ ПО КЛАССАМ**",
            value=" ",
            inline=False,
        )
        for cls, members, limit in accepted_classes[:24]:
            if getattr(cls, "limit_count", 0):
                field_name = f"{cls.icon} {cls.name} [{len(members)}/{limit}]"
            else:
                field_name = f"{cls.icon} {cls.name}"
            embed.add_field(
                name=field_name,
                value=_numbered_participants(members)[:1000],
                inline=True,
            )
    else:
        embed.add_field(
            name="**СОСТАВ ПО КЛАССАМ**",
            value="Пока никто не записался.",
            inline=False,
        )

    backup_by_class = defaultdict(list)
    for signup in raid.signups:
        if signup.status == "backup":
            backup_by_class[signup.class_id].append(signup)

    backup_classes = []
    for cls in raid_classes:
        members = backup_by_class.get(cls.id, [])
        if members:
            backup_classes.append((cls, members))

    if backup_classes:
        embed.add_field(name="**ЗАПАСНЫЕ**", value=" ", inline=False)
        for cls, members in backup_classes[:12]:
            embed.add_field(
                name=f"🪑 {cls.icon} {cls.name}",
                value=_numbered_participants(members)[:1000],
                inline=True,
            )

    maybe = [s for s in raid.signups if s.status == "maybe"]
    if maybe:
        embed.add_field(
            name="**ВОЗМОЖНО БУДУТ**",
            value=_numbered_participants(maybe)[:1000],
            inline=False,
        )

    declined = [s for s in raid.signups if s.status == "declined"]
    if declined:
        embed.add_field(
            name="**ТОЧНО НЕ БУДУТ**",
            value=_numbered_participants(declined)[:1000],
            inline=False,
        )

    embed.set_footer(text="SP4RK • Stormchasers • Запись через кнопки ниже.")
    return embed


async def refresh_raid_message(bot: discord.Client, raid_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        raid = await raid_repo.get_raid(session, raid_id)
        if not raid or not raid.message_id:
            return
        raid_classes = await class_repo.list_classes(session, raid.guild_id)

    channel = bot.get_channel(raid.channel_id) or await bot.fetch_channel(raid.channel_id)
    message = await channel.fetch_message(raid.message_id)
    from app.bot.ui import build_signup_view
    await message.edit(
        embed=build_raid_embed(raid, raid_classes),
        view=build_signup_view(
            raid.id,
            raid_classes,
            disabled=not is_registration_open(raid),
        ),
        allowed_mentions=discord.AllowedMentions.none(),
    )
