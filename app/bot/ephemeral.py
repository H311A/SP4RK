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
    kwargs["ephemeral"] = True
    kwargs["wait"] = True
    message = await interaction.followup.send(*args, **kwargs)
    schedule_delete_message(message, delete_after)
    return message


class AutoExpireView(discord.ui.View):
    def __init__(self, *, timeout: float | None = None):
        super().__init__(timeout=timeout or settings.menu_idle_timeout_seconds)
        self._owner_interaction: discord.Interaction | None = None

    def bind(self, interaction: discord.Interaction) -> None:
        self._owner_interaction = interaction

    async def on_timeout(self) -> None:
        if self._owner_interaction is None:
            return
        try:
            await self._owner_interaction.delete_original_response()
        except (discord.NotFound, discord.HTTPException, discord.Forbidden):
            pass


async def show_screen(interaction: discord.Interaction, *, embed=None, content=None, view=None):
    try:
        if not interaction.response.is_done():
            await interaction.response.edit_message(content=content, embed=embed, view=view)
        else:
            await interaction.edit_original_response(content=content, embed=embed, view=view)
    except (discord.NotFound, discord.HTTPException) as exc:
        log.warning("show_screen could not update message, likely already removed: %s", exc)
        try:
            await send_ephemeral_followup(
                interaction, "Это меню уже устарело, вызови его заново через /spark."
            )
        except (discord.NotFound, discord.HTTPException):
            pass
        return

    if isinstance(view, AutoExpireView):
        view.bind(interaction)


def install_ephemeral_autodelete_patch() -> None:
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
