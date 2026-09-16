import io

import discord

from app.bot import formatting as fmt


def build_roster_file(raid, classes) -> discord.File:
    lines = [raid.title, f"Дата (UTC): {raid.starts_at.isoformat(sep=' ', timespec='minutes')}", ""]

    accepted = fmt.sorted_signups(raid.signups, "accepted")
    by_class: dict = {c.id: [] for c in classes}
    unassigned = []
    for s in accepted:
        (by_class[s.class_id] if s.class_id in by_class else unassigned).append(s)

    lines.append(f"Основной состав ({len(accepted)}):")
    for cls in classes:
        members = by_class.get(cls.id, [])
        if not members:
            continue
        lines.append(f"  {cls.name}:")
        for s in members:
            lines.append(f"    - {s.display_name} (id {s.user_id})")
    if unassigned:
        lines.append("  Без класса:")
        for s in unassigned:
            lines.append(f"    - {s.display_name} (id {s.user_id})")

    for status, label in (
        ("backup", "Запас"),
        ("maybe", "Возможно"),
        ("declined", "Не пойдут"),
    ):
        members = fmt.sorted_signups(raid.signups, status)
        if not members:
            continue
        lines.append("")
        lines.append(f"{label} ({len(members)}):")
        for s in members:
            lines.append(f"  - {s.display_name} (id {s.user_id})")

    content = "\n".join(lines)
    buffer = io.BytesIO(content.encode("utf-8"))
    return discord.File(buffer, filename="roster.txt")
