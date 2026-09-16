from typing import Awaitable, Callable

import discord

from app.bot.ephemeral import AutoExpireView, send_ephemeral_followup


class ConfirmView(AutoExpireView):
    def __init__(
        self,
        on_confirm: Callable[[discord.Interaction], Awaitable[None]],
        on_cancel: Callable[[discord.Interaction], Awaitable[None]] | None = None,
        confirm_label: str = "Подтвердить",
        cancel_label: str = "Отмена",
        confirm_style: discord.ButtonStyle = discord.ButtonStyle.danger,
    ):
        super().__init__()
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel

        confirm_button: discord.ui.Button = discord.ui.Button(label=confirm_label, style=confirm_style, emoji="✅")
        cancel_button: discord.ui.Button = discord.ui.Button(
            label=cancel_label, style=discord.ButtonStyle.secondary, emoji="✖️"
        )

        async def _confirm(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            await self.on_confirm(interaction)

        async def _cancel(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            if self.on_cancel is not None:
                await self.on_cancel(interaction)
            else:
                await send_ephemeral_followup(interaction, "Отменено, ничего не трогал.")

        confirm_button.callback = _confirm
        cancel_button.callback = _cancel
        self.add_item(confirm_button)
        self.add_item(cancel_button)


class ContinueToModalView(AutoExpireView):
    def __init__(self, build_modal: Callable[[], discord.ui.Modal], label: str = "Продолжить"):
        super().__init__()
        self.build_modal = build_modal

        button: discord.ui.Button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, emoji="➡️")

        async def _continue(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(self.build_modal())

        button.callback = _continue
        self.add_item(button)
