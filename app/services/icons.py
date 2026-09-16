import logging
import re
import uuid

import discord

from app.bot.icons.processor import fit_icon

log = logging.getLogger("SP4RK.icons")


def _emoji_name(hint: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]", "", hint.replace(" ", "_"))[:20] or "class"
    suffix = uuid.uuid4().hex[:8]
    return f"{base}_{suffix}"[:32]


async def create_class_icon(bot: discord.Client, name_hint: str, raw_bytes: bytes) -> tuple[int, str] | None:
    try:
        fitted = fit_icon(raw_bytes)
        emoji_name = _emoji_name(name_hint)
        emoji = await bot.create_application_emoji(name=emoji_name, image=fitted)
        return emoji.id, emoji.name
    except Exception as exc:
        log.warning("Could not create application emoji for class icon: %s", exc)
        return None


async def delete_class_icon(bot: discord.Client, emoji_id: int | None) -> None:
    if not emoji_id:
        return
    try:
        emoji = await bot.fetch_application_emoji(emoji_id)
        await emoji.delete()
    except Exception as exc:
        log.warning("Could not delete application emoji %s: %s", emoji_id, exc)
