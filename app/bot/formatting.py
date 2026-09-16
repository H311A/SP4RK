from datetime import datetime, timedelta

import discord

RED = 0xE74C3C
AMBER = 0xF1C40F
GREY = 0x99AAB5


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    n_abs = abs(n)
    if 11 <= n_abs % 100 <= 14:
        return many
    last = n_abs % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def minutes_phrase(minutes: int) -> str:
    return f"{minutes} {plural_ru(minutes, 'минуту', 'минуты', 'минут')}"


def hours_phrase(hours: int) -> str:
    return f"{hours} {plural_ru(hours, 'час', 'часа', 'часов')}"


def duration_phrase(total_minutes: int) -> str:
    hours, minutes = divmod(max(total_minutes, 0), 60)
    parts = []
    if hours:
        parts.append(hours_phrase(hours))
    if minutes or not parts:
        parts.append(minutes_phrase(minutes))
    return " ".join(parts)


def safe_display_name(display_name: str | None, user_id: int) -> str:
    name = (display_name or "").strip()
    if not name:
        return f"ID {user_id}"
    name = discord.utils.escape_markdown(name)
    name = discord.utils.escape_mentions(name)
    if len(name) > 80:
        name = name[:77] + "..."
    return name


def safe_embed_title(title: str, limit: int = 240) -> tuple[str, str | None]:
    title = (title or "").strip() or "Событие"
    if len(title) <= limit:
        return title, None
    return title[: limit - 1] + "…", title


def sorted_signups(signups, status: str | None = None):
    items = [s for s in signups if status is None or s.status == status]
    return sorted(items, key=lambda s: (s.joined_at is None, s.joined_at or datetime.min))


def class_icon_text(cls) -> str:
    if cls is None:
        return ""
    if cls.icon_emoji_id and cls.icon_emoji_name:
        return f"<:{cls.icon_emoji_name}:{cls.icon_emoji_id}>"
    return cls.icon or "⚡"


def class_emoji(cls):
    if cls is not None and cls.icon_emoji_id and cls.icon_emoji_name:
        return discord.PartialEmoji(name=cls.icon_emoji_name, id=cls.icon_emoji_id)
    return (cls.icon if cls else None) or "⚡"


def participant_link(signup) -> str:
    name = safe_display_name(signup.display_name, signup.user_id)
    return f"[{name}](https://discord.com/users/{signup.user_id})"


def limit_text(limit_count: int) -> str:
    return "∞" if not limit_count else str(limit_count)


def status_text(raid, open_now: bool) -> tuple[str, int]:
    if raid.cancelled:
        return "отменена", RED
    if raid.archived:
        return "завершена", GREY
    if raid.registration_closed:
        return "закрыта досрочно", AMBER
    if not open_now:
        return "закрыта", AMBER
    return "открыта", 0


def status_dot(color: int) -> str:
    if color == RED:
        return "🔴"
    if color == AMBER:
        return "🟡"
    if color == GREY:
        return "⚪"
    return "🟢"


def is_open_now(raid) -> bool:
    if raid.cancelled or raid.archived or raid.registration_closed:
        return False
    return datetime.utcnow() < raid.starts_at - timedelta(minutes=1)
