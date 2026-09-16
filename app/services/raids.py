import io
import logging

import discord

from app.bot import formatting as fmt
from app.bot.roles import ROLE_LABELS, ROLE_ORDER
from app.config import settings
from app.database.session import SessionLocal
from app.repositories.classes import list_classes
from app.repositories.raids import get_raid
from app.services import banners
from app.utils.time import discord_ts, short_id

log = logging.getLogger("SP4RK.raids")

FIELD_VALUE_LIMIT = 1024


def _truncate(value: str, limit: int = FIELD_VALUE_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def banner_filename(raid_id) -> str:
    return f"banner_{raid_id.hex}.png"


def _class_icon_or_fallback(cls) -> str:
    return fmt.class_icon_text(cls) if cls is not None else "❔"


def _cluster_by_class(entries: list) -> list:
    order = []
    grouped: dict = {}
    for s, cls in entries:
        key = cls.id if cls is not None else None
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append((s, cls))
    return [pair for key in order for pair in grouped[key]]


def _group_by_role(signups, classes_by_id: dict) -> list[tuple[str, list]]:
    buckets: dict[str | None, list] = {}
    for s in signups:
        cls = classes_by_id.get(s.class_id)
        role = cls.role if cls else None
        buckets.setdefault(role, []).append((s, cls))

    blocks = []
    for role in ROLE_ORDER:
        entries = buckets.get(role)
        if not entries:
            continue
        blocks.append((ROLE_LABELS[role], _cluster_by_class(entries)))
    return blocks


def _group_by_role_detailed(signups, classes_by_id: dict) -> list[tuple[str, str]]:
    buckets: dict[str | None, dict] = {}
    for s in signups:
        cls = classes_by_id.get(s.class_id)
        role = cls.role if cls else None
        by_class = buckets.setdefault(role, {})
        by_class.setdefault(s.class_id, {"cls": cls, "members": []})
        by_class[s.class_id]["members"].append(s)

    blocks = []
    for role in ROLE_ORDER:
        by_class = buckets.get(role)
        if not by_class:
            continue
        parts = []
        for entry in by_class.values():
            cls = entry["cls"]
            header = f"**{fmt.class_icon_text(cls)} {cls.name}**" if cls is not None else "**Без класса**"
            body = "\n".join(fmt.participant_link(s) for s in entry["members"])
            parts.append(f"{header}\n{body}")
        blocks.append((ROLE_LABELS[role], "\n\n".join(parts)))
    return blocks


def build_roster_breakdown_embed(raid, classes) -> discord.Embed:
    accepted = fmt.sorted_signups(raid.signups, "accepted")
    backup = fmt.sorted_signups(raid.signups, "backup")
    maybe = fmt.sorted_signups(raid.signups, "maybe")
    classes_by_id = {c.id: c for c in classes}

    title, _overflow = fmt.safe_embed_title(raid.title)
    embed = discord.Embed(title=f"Участники: {title}", color=settings.brand_color)

    sections = [
        ("СОСТАВ ПО КЛАССАМ", accepted),
        ("ЗАПАСНЫЕ", backup),
        ("ВОЗМОЖНО БУДУТ", maybe),
    ]
    for section_name, signups in sections:
        if not signups:
            continue
        blocks = _group_by_role_detailed(signups, classes_by_id)
        text = "\n\n".join(f"**{label}**\n{block}" for label, block in blocks)
        embed.add_field(name=section_name, value=_truncate(text), inline=False)

    if not any(signups for _name, signups in sections):
        embed.description = "Пока никто не записался."

    return embed


def build_raid_embed(raid, classes) -> discord.Embed:
    open_now = fmt.is_open_now(raid)
    status_word, status_color = fmt.status_text(raid, open_now)
    dot = fmt.status_dot(status_color)
    title, overflow = fmt.safe_embed_title(raid.title)

    description_parts = []
    if raid.description:
        description_parts.append(raid.description)
    if overflow:
        description_parts.append(overflow)
    description = "\n\n".join(description_parts) if description_parts else None

    if status_color:
        embed_color = status_color
    elif raid.game:
        embed_color = raid.game.color
    else:
        embed_color = settings.brand_color

    embed = discord.Embed(title=title, description=description, color=embed_color)

    info_lines = [
        f"{dot} Регистрация {status_word}.",
        f"\U0001F550 Начало: {discord_ts(raid.starts_at, 'F')}.",
        f"⏳ Начнётся: {discord_ts(raid.starts_at, 'R')}.",
        f"\U0001F3C1 Окончание: {discord_ts(raid.ends_at, 'f')}.",
        "",
        f"\U0001F512 Запись закрывается: за 1 минуту до начала.",
        f"\U0001F514 ЛС-напоминание: за {fmt.minutes_phrase(raid.reminder_minutes)} до начала.",
    ]
    embed.add_field(name="ИНФОРМАЦИЯ", value="\n".join(info_lines), inline=False)

    accepted = fmt.sorted_signups(raid.signups, "accepted")
    backup = fmt.sorted_signups(raid.signups, "backup")
    maybe = fmt.sorted_signups(raid.signups, "maybe")
    declined = fmt.sorted_signups(raid.signups, "declined")
    total_limit = fmt.limit_text(raid.participant_limit)

    classes_by_id = {c.id: c for c in classes}

    if accepted:
        embed.add_field(
            name="ОСНОВНОЙ СОСТАВ", value=f"Занято {len(accepted)} из {total_limit}.", inline=False
        )
        for role_label, entries in _group_by_role(accepted, classes_by_id):
            lines = [f"{_class_icon_or_fallback(cls)} {fmt.participant_link(s)}" for s, cls in entries]
            embed.add_field(
                name=f"{role_label} ({len(entries)})", value=_truncate("\n".join(lines)), inline=False
            )

    if backup:
        lines = [f"{_class_icon_or_fallback(classes_by_id.get(s.class_id))} {fmt.participant_link(s)}" for s in backup]
        embed.add_field(name=f"ЗАПАСНЫЕ ({len(backup)})", value=_truncate("\n".join(lines)), inline=False)

    if maybe:
        line = " ".join(
            f"{_class_icon_or_fallback(classes_by_id.get(s.class_id))} {fmt.participant_link(s)}" for s in maybe
        )
        embed.add_field(name=f"ВОЗМОЖНО БУДУТ ({len(maybe)})", value=_truncate(line), inline=False)

    if declined:
        line = ", ".join(fmt.participant_link(s) for s in declined)
        embed.add_field(name=f"ТОЧНО НЕ БУДУТ ({len(declined)})", value=_truncate(line), inline=False)

    game_label = f"{raid.game.icon} {raid.game.name}" if raid.game else ""
    embed.set_footer(text=f"ID {short_id(raid.id)} · {game_label}")
    return embed


def build_message_payload(raid, classes) -> tuple[discord.Embed, list[discord.Embed], list[discord.File]]:
    main_embed = build_raid_embed(raid, classes)
    files: list[discord.File] = []

    banner_bytes = banners.read_banner(raid.banner_path)
    if banner_bytes:
        filename = banner_filename(raid.id)
        files.append(discord.File(io.BytesIO(banner_bytes), filename=filename))
        main_embed.set_image(url=f"attachment://{filename}")

    return main_embed, [main_embed], files


async def refresh_raid_message(bot: discord.Client, raid_id) -> None:
    from app.bot.views.signup import build_signup_view

    async with SessionLocal() as session:
        raid = await get_raid(session, raid_id)
        if raid is None:
            return
        classes = await list_classes(session, raid.game_id, active_only=False)
        session.expunge_all()

    if not raid.channel_id or not raid.message_id:
        return

    try:
        channel = bot.get_channel(raid.channel_id) or await bot.fetch_channel(raid.channel_id)
        message = await channel.fetch_message(raid.message_id)
    except (discord.NotFound, discord.Forbidden):
        return

    _main_embed, embeds, files = build_message_payload(raid, classes)
    open_now = fmt.is_open_now(raid)
    view = build_signup_view(raid.id, classes, disabled=not open_now)

    await message.edit(embeds=embeds, attachments=files, view=view)
