import asyncio
import logging

import discord

from app.config import settings

log = logging.getLogger("SP4RK.ephemeral")


def _delay(value: int | None = None) -> int:
    try:
        return int(settings.ephemeral_delete_after if value is None else value)
    except Exception:
        return 60


async def _delete_original_later(interaction: discord.Interaction, delay: int | None = None) -> None:
    seconds = _delay(delay)
    if seconds <= 0:
        return
    await asyncio.sleep(seconds)
    try:
        await interaction.delete_original_response()
    except (discord.NotFound, discord.HTTPException, discord.Forbidden):
        pass
    except Exception as exc:
        log.debug("Could not delete ephemeral original response: %s", exc)


async def _delete_message_later(message, delay: int | None = None) -> None:
    seconds = _delay(delay)
    if seconds <= 0:
        return
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except (discord.NotFound, discord.HTTPException, discord.Forbidden):
        pass
    except Exception as exc:
        log.debug("Could not delete ephemeral followup response: %s", exc)


def schedule_delete_original(interaction: discord.Interaction, delay: int | None = None) -> None:
    try:
        asyncio.create_task(_delete_original_later(interaction, delay))
    except RuntimeError:
        pass


def schedule_delete_message(message, delay: int | None = None) -> None:
    try:
        asyncio.create_task(_delete_message_later(message, delay))
    except RuntimeError:
        pass


async def send_ephemeral_followup(interaction: discord.Interaction, *args, delete_after: int | None = None, **kwargs):
    """Send an ephemeral followup and delete it after EPHEMERAL_DELETE_AFTER seconds.

    Discord.py's `delete_after` is not reliable for ephemeral interaction replies in all versions,
    so we request the returned webhook message with `wait=True` and delete it manually.
    """
    kwargs["ephemeral"] = True
    kwargs["wait"] = True
    message = await interaction.followup.send(*args, **kwargs)
    schedule_delete_message(message, delete_after)
    return message


def install_ephemeral_autodelete_patch() -> None:
    """Make InteractionResponse.send_message(..., ephemeral=True, delete_after=N) reliable.

    Existing code can continue to pass `delete_after=EPHEMERAL_DELETE_AFTER`. For ephemeral
    responses we remove the parameter before calling discord.py and delete the original
    interaction response ourselves after the configured delay.
    """
    if getattr(discord.InteractionResponse.send_message, "_sp4rk_ephemeral_patch", False):
        return

    original_send_message = discord.InteractionResponse.send_message

    async def patched_send_message(self, *args, **kwargs):
        delete_after = kwargs.get("delete_after")
        ephemeral = bool(kwargs.get("ephemeral", False))

        if ephemeral and delete_after is not None:
            kwargs.pop("delete_after", None)
            result = await original_send_message(self, *args, **kwargs)
            interaction = getattr(self, "_parent", None)
            if interaction is not None:
                schedule_delete_original(interaction, delete_after)
            return result

        return await original_send_message(self, *args, **kwargs)

    patched_send_message._sp4rk_ephemeral_patch = True
    discord.InteractionResponse.send_message = patched_send_message
