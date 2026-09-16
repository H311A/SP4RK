from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.attendance import top_attendees, user_stats

STATUS_LABELS = {
    "accepted": "В составе",
    "backup": "В запасе",
    "maybe": "Возможно",
    "declined": "Не придёт",
}


async def build_top_text(session: AsyncSession, guild_id: int) -> str:
    top = await top_attendees(session, guild_id, limit=10)
    if not top:
        return "Пока нет данных для статистики."
    lines = ["Чаще всего участвуют в основном составе:"]
    for i, (_user_id, name, count) in enumerate(top, start=1):
        lines.append(f"{i}. {name} - {count}")
    return "\n".join(lines)


async def build_personal_text(session: AsyncSession, guild_id: int, user_id: int) -> str:
    stats = await user_stats(session, guild_id, user_id)
    if not stats:
        return "У тебя пока нет истории участия в событиях."
    lines = ["Твоя статистика:"]
    for status, label in STATUS_LABELS.items():
        if status in stats:
            lines.append(f"{label}: {stats[status]}")
    return "\n".join(lines)
