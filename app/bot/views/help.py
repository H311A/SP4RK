import discord

from app.bot.ephemeral import send_ephemeral_followup
from app.bot.faq import build_faq_embed, faq_select_options


class FAQSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Выбери тему", options=faq_select_options(), min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        embed = build_faq_embed(self.values[0])
        await interaction.response.edit_message(embed=embed, view=self.view)


class FAQView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(FAQSelect())


async def send_faq_hub(interaction: discord.Interaction) -> None:
    await send_ephemeral_followup(interaction, "О чём рассказать?", view=FAQView())
