import discord

from app.bot import formatting as fmt
from app.bot.banners.upload_flow import (
    BannerUploadCancelled,
    BannerUploadInvalid,
    BannerUploadTimeout,
    collect_image_via_dm,
    icon_hint_text,
)
from app.bot.ephemeral import AutoExpireView, send_ephemeral_followup, show_screen
from app.bot.modals import ClassCreateModal, GameColorModal
from app.bot.roles import ROLE_CHOICES, ROLE_LABELS_SHORT
from app.bot.views.confirm import ConfirmView
from app.config import settings
from app.database.models import GameClass
from app.database.session import SessionLocal
from app.repositories.classes import create_class, delete_class, get_class, list_classes, list_specs, set_class_role
from app.repositories.games import delete_game, get_game, set_game_active, set_game_color
from app.repositories.raids import has_active_raids_for_game, list_active_raid_ids_for_game
from app.services import icons as icons_service
from app.services.raids import refresh_raid_message


def _describe_class(cls: GameClass) -> str:
    state = "" if cls.is_active else " (скрыт)"
    limit_part = f" - лимит {cls.limit_count}" if cls.limit_count else ""
    role_part = f" - {ROLE_LABELS_SHORT[cls.role]}" if cls.role else ""
    return f"{fmt.class_icon_text(cls)} {cls.name}{limit_part}{role_part}{state}"


async def _build_game_detail_screen(game) -> tuple[discord.Embed, "GameDetailView"]:
    async with SessionLocal() as session:
        fresh = await get_game(session, game.id)
        classes = await list_classes(session, game.id, active_only=False)
    game = fresh or game

    embed = discord.Embed(title=f"{game.icon} {game.name}", color=game.color or settings.brand_color)
    if not classes:
        embed.description = "У игры пока нет классов."
    else:
        top_level = [c for c in classes if c.parent_class_id is None]
        specs_by_parent: dict = {}
        for c in classes:
            if c.parent_class_id is not None:
                specs_by_parent.setdefault(c.parent_class_id, []).append(c)

        lines = []
        for c in top_level:
            lines.append(_describe_class(c))
            for spec in specs_by_parent.get(c.id, []):
                lines.append(f"⤷ {_describe_class(spec)}")
        embed.description = "\n".join(lines)

    return embed, GameDetailView(game, classes)


async def send_game_detail(interaction: discord.Interaction, game) -> None:
    embed, view = await _build_game_detail_screen(game)
    await show_screen(interaction, embed=embed, view=view)


class GameDetailView(AutoExpireView):
    def __init__(self, game, classes):
        super().__init__()
        self.game = game
        self.classes = classes
        top_level = [c for c in classes if c.parent_class_id is None]
        if top_level:
            self.add_item(ClassManageSelect(game, top_level))

    @discord.ui.button(label="Назад к играм", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.bot.views.games import send_games_menu

        await send_games_menu(interaction)

    @discord.ui.button(label="Добавить класс", emoji="➕", style=discord.ButtonStyle.primary, row=2)
    async def add_class(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        top_level = [c for c in self.classes if c.parent_class_id is None]
        if not top_level:
            await interaction.response.send_modal(ClassCreateModal(self._make_on_submit(None)))
            return

        await show_screen(
            interaction,
            content="Новый класс или спек уже существующего?",
            embed=None,
            view=AddClassChoiceView(self.game, top_level, self._make_on_submit),
        )

    @discord.ui.button(label="Скрыть/показать игру", emoji="\U0001F441️", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_game(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async with SessionLocal() as session:
            game = await get_game(session, self.game.id)
            if game is None:
                await show_screen(interaction, content="Игра не найдена.", embed=None, view=None)
                return
            await set_game_active(session, game, not game.is_active)
            await session.commit()

        embed, view = await _build_game_detail_screen(self.game)
        await show_screen(interaction, embed=embed, view=view)

    @discord.ui.button(label="Изменить цвет", emoji="\U0001F3A8", style=discord.ButtonStyle.secondary, row=1)
    async def change_color(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        game = self.game

        async def on_submit(inner_interaction: discord.Interaction, color: int) -> None:
            raid_ids = []
            async with SessionLocal() as session:
                fresh = await get_game(session, game.id)
                if fresh is None:
                    await inner_interaction.response.send_message("Игра не найдена.", ephemeral=True)
                    return
                await set_game_color(session, fresh, color)
                await session.commit()
                raid_ids = await list_active_raid_ids_for_game(session, game.id)

            for raid_id in raid_ids:
                await refresh_raid_message(inner_interaction.client, raid_id)

            embed, view = await _build_game_detail_screen(game)
            await inner_interaction.response.edit_message(embed=embed, view=view)

        await interaction.response.send_modal(GameColorModal(game.color, on_submit))

    @discord.ui.button(label="Удалить игру", emoji="\U0001F5D1️", style=discord.ButtonStyle.danger, row=1)
    async def delete_game_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        game_id = self.game.id
        game_label = f"{self.game.icon} {self.game.name}"

        async with SessionLocal() as session:
            if await has_active_raids_for_game(session, game_id):
                await show_screen(
                    interaction,
                    content=(
                        "По этой игре есть активные события. Заверши или отмени их, "
                        "потом можно будет удалить игру."
                    ),
                    embed=None,
                    view=None,
                )
                return

        async def do_delete(inner_interaction: discord.Interaction) -> None:
            async with SessionLocal() as session:
                game = await get_game(session, game_id)
                if game:
                    await delete_game(session, game)
                    await session.commit()
            from app.bot.views.games import send_games_menu

            await send_games_menu(inner_interaction)

        async def do_cancel(inner_interaction: discord.Interaction) -> None:
            embed, view = await _build_game_detail_screen(self.game)
            await show_screen(inner_interaction, embed=embed, view=view)

        await show_screen(
            interaction,
            content=f"Точно удалить игру {game_label}? Удалятся все её классы и шаблоны. Отменить нельзя.",
            embed=None,
            view=ConfirmView(on_confirm=do_delete, on_cancel=do_cancel),
        )

    def _make_on_submit(self, parent_class_id):
        game = self.game

        async def on_submit(inner_interaction: discord.Interaction, name: str, limit: int) -> None:
            self.stop()
            await inner_interaction.response.edit_message(
                content=f"Класс **{name}** почти готов. Проверь личные сообщения от бота.",
                embed=None,
                view=None,
            )
            try:
                raw = await collect_image_via_dm(inner_interaction.client, inner_interaction.user, icon_hint_text())
            except (BannerUploadTimeout, BannerUploadCancelled):
                await _ask_role_and_create(inner_interaction, game, name, limit, None, parent_class_id)
                return
            except BannerUploadInvalid as exc:
                await send_ephemeral_followup(inner_interaction, str(exc))
                await _ask_role_and_create(inner_interaction, game, name, limit, None, parent_class_id)
                return

            emoji_pair = await icons_service.create_class_icon(inner_interaction.client, name, raw)
            if emoji_pair is None:
                await send_ephemeral_followup(
                    inner_interaction, "Не получилось загрузить иконку, класс создам с обычным эмодзи."
                )
            await _ask_role_and_create(inner_interaction, game, name, limit, emoji_pair, parent_class_id)

        return on_submit


class AddClassChoiceView(AutoExpireView):
    def __init__(self, game, top_level_classes, make_on_submit):
        super().__init__()
        self.game = game
        self.top_level_classes = top_level_classes
        self.make_on_submit = make_on_submit

    @discord.ui.button(label="Новый класс", emoji="➕", style=discord.ButtonStyle.primary)
    async def new_class(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ClassCreateModal(self.make_on_submit(None), title="Новый класс"))

    @discord.ui.button(label="Спек класса", emoji="\U0001F9EC", style=discord.ButtonStyle.secondary)
    async def new_spec(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await show_screen(
            interaction,
            content="Для какого класса добавляем спек?",
            embed=None,
            view=ParentClassSelectView(self.game, self.top_level_classes, self.make_on_submit),
        )


class ParentClassSelectView(discord.ui.View):
    def __init__(self, game, top_level_classes, make_on_submit):
        super().__init__(timeout=120)
        self.add_item(_ParentClassSelect(game, top_level_classes, make_on_submit))


class _ParentClassSelect(discord.ui.Select):
    def __init__(self, game, top_level_classes, make_on_submit):
        options = [
            discord.SelectOption(label=c.name[:100], value=str(c.id), emoji=fmt.class_emoji(c))
            for c in top_level_classes[:25]
        ]
        super().__init__(placeholder="Класс", options=options)
        self.game = game
        self.classes_by_id = {str(c.id): c for c in top_level_classes}
        self.make_on_submit = make_on_submit

    async def callback(self, interaction: discord.Interaction) -> None:
        cls = self.classes_by_id[self.values[0]]
        await interaction.response.send_modal(
            ClassCreateModal(self.make_on_submit(cls.id), title=f"Спек: {cls.name}"[:45])
        )


class RoleChoiceView(discord.ui.View):
    def __init__(self, on_pick):
        super().__init__(timeout=120)
        self.on_pick = on_pick
        for value, label in ROLE_CHOICES:
            self.add_item(_RoleButton(value, label, on_pick))


class _RoleButton(discord.ui.Button):
    def __init__(self, value: str, label: str, on_pick):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.value = value
        self.on_pick = on_pick

    async def callback(self, interaction: discord.Interaction) -> None:
        role = None if self.value == "none" else self.value
        await self.on_pick(interaction, role)


async def _ask_role_and_create(
    interaction: discord.Interaction,
    game,
    name: str,
    limit: int,
    emoji_pair: tuple[int, str] | None,
    parent_class_id,
) -> None:
    async def on_pick(inner_interaction: discord.Interaction, role: str | None) -> None:
        await _create_class_and_show(inner_interaction, game, name, limit, emoji_pair, parent_class_id, role)

    await show_screen(interaction, content=f"Какая роль у **{name}**?", embed=None, view=RoleChoiceView(on_pick))


async def _create_class_and_show(
    interaction: discord.Interaction,
    game,
    name: str,
    limit: int,
    emoji_pair: tuple[int, str] | None,
    parent_class_id,
    role: str | None,
) -> None:
    async with SessionLocal() as session:
        emoji_id, emoji_name = emoji_pair if emoji_pair else (None, None)
        cls = await create_class(
            session, game.id, name, "⚡", limit, interaction.user.id, parent_class_id=parent_class_id, role=role
        )
        cls.icon_emoji_id = emoji_id
        cls.icon_emoji_name = emoji_name
        await session.commit()

    embed, view = await _build_game_detail_screen(game)
    await show_screen(interaction, embed=embed, view=view)


class ClassManageSelect(discord.ui.Select):
    def __init__(self, game, classes):
        options = [
            discord.SelectOption(label=c.name[:100], value=str(c.id), emoji=fmt.class_emoji(c))
            for c in classes[:25]
        ]
        super().__init__(placeholder="Класс…", options=options, row=3)
        self.game = game
        self.classes_by_id = {str(c.id): c for c in classes}

    async def callback(self, interaction: discord.Interaction) -> None:
        cls = self.classes_by_id[self.values[0]]
        await show_screen(
            interaction,
            content=f"Что сделать с **{cls.name}**?",
            embed=None,
            view=ClassActionView(self.game, cls),
        )


class ClassActionView(AutoExpireView):
    def __init__(self, game, cls):
        super().__init__()
        self.game = game
        self.cls = cls
        if cls.parent_class_id is None:
            self.add_item(_SpecsButton(game, cls))

    @discord.ui.button(label="Изменить иконку", emoji="\U0001F5BC️", style=discord.ButtonStyle.primary, row=0)
    async def change_icon(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        game = self.game
        cls_id = self.cls.id
        cls_name = self.cls.name

        await interaction.response.edit_message(
            content=f"Пришли новую картинку для **{cls_name}** в личные сообщения.", embed=None, view=None
        )

        try:
            raw = await collect_image_via_dm(interaction.client, interaction.user, icon_hint_text())
        except (BannerUploadTimeout, BannerUploadCancelled):
            await send_ephemeral_followup(interaction, "Не стала менять иконку.")
            return
        except BannerUploadInvalid as exc:
            await send_ephemeral_followup(interaction, str(exc))
            return

        emoji_pair = await icons_service.create_class_icon(interaction.client, cls_name, raw)
        if emoji_pair is None:
            await send_ephemeral_followup(interaction, "Не получилось загрузить новую иконку.")
            return

        raid_ids = []
        async with SessionLocal() as session:
            fresh = await get_class(session, cls_id)
            if fresh is None:
                await send_ephemeral_followup(interaction, "Этот класс уже удалён.")
                return
            old_emoji_id = fresh.icon_emoji_id
            fresh.icon_emoji_id, fresh.icon_emoji_name = emoji_pair
            await session.commit()
            raid_ids = await list_active_raid_ids_for_game(session, game.id)

        if old_emoji_id:
            await icons_service.delete_class_icon(interaction.client, old_emoji_id)

        for raid_id in raid_ids:
            await refresh_raid_message(interaction.client, raid_id)

        embed, view = await _build_game_detail_screen(game)
        await show_screen(interaction, embed=embed, view=view)

    @discord.ui.button(label="Изменить роль", emoji="\U0001F3AF", style=discord.ButtonStyle.secondary, row=0)
    async def change_role(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        game = self.game
        cls = self.cls

        async def on_pick(inner_interaction: discord.Interaction, role: str | None) -> None:
            raid_ids = []
            async with SessionLocal() as session:
                fresh = await get_class(session, cls.id)
                if fresh:
                    await set_class_role(session, fresh, role)
                    await session.commit()
                    raid_ids = await list_active_raid_ids_for_game(session, game.id)

            for raid_id in raid_ids:
                await refresh_raid_message(inner_interaction.client, raid_id)

            embed, view = await _build_game_detail_screen(game)
            await show_screen(inner_interaction, embed=embed, view=view)

        await show_screen(
            interaction, content=f"Какая роль у **{cls.name}**?", embed=None, view=RoleChoiceView(on_pick)
        )

    @discord.ui.button(label="Удалить", emoji="\U0001F5D1️", style=discord.ButtonStyle.danger, row=0)
    async def delete(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        game = self.game
        cls = self.cls

        async def do_delete(inner_interaction: discord.Interaction) -> None:
            raid_ids = []
            async with SessionLocal() as session:
                fresh = await session.get(GameClass, cls.id)
                if fresh:
                    emoji_id = fresh.icon_emoji_id
                    await delete_class(session, fresh)
                    await session.commit()
                    await icons_service.delete_class_icon(inner_interaction.client, emoji_id)
                    raid_ids = await list_active_raid_ids_for_game(session, game.id)

            for raid_id in raid_ids:
                await refresh_raid_message(inner_interaction.client, raid_id)

            embed, view = await _build_game_detail_screen(game)
            await show_screen(inner_interaction, embed=embed, view=view)

        async def do_cancel(inner_interaction: discord.Interaction) -> None:
            embed, view = await _build_game_detail_screen(game)
            await show_screen(inner_interaction, embed=embed, view=view)

        await show_screen(
            interaction,
            content=f"Точно удалить **{cls.name}**? Если это класс со спеками, они останутся, просто "
            "станут отдельными классами.",
            embed=None,
            view=ConfirmView(on_confirm=do_delete, on_cancel=do_cancel),
        )

    @discord.ui.button(label="Назад", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        embed, view = await _build_game_detail_screen(self.game)
        await show_screen(interaction, embed=embed, view=view)


class _SpecsButton(discord.ui.Button):
    def __init__(self, game, cls):
        super().__init__(label="Спеки", emoji="\U0001F9EC", style=discord.ButtonStyle.secondary, row=0)
        self.game = game
        self.cls = cls

    async def callback(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            specs = await list_specs(session, self.cls.id, active_only=False)

        if not specs:
            await show_screen(
                interaction,
                content=f"У класса **{self.cls.name}** пока нет спеков.",
                embed=None,
                view=ClassActionView(self.game, self.cls),
            )
            return

        await show_screen(
            interaction,
            content=f"Спек класса **{self.cls.name}**:",
            embed=None,
            view=SpecManageSelectView(self.game, self.cls, specs),
        )


class SpecManageSelectView(discord.ui.View):
    def __init__(self, game, parent_cls, specs):
        super().__init__(timeout=120)
        self.add_item(_SpecManageSelect(game, specs))
        self.add_item(_BackToClassButton(game, parent_cls))


class _SpecManageSelect(discord.ui.Select):
    def __init__(self, game, specs):
        options = [
            discord.SelectOption(label=s.name[:100], value=str(s.id), emoji=fmt.class_emoji(s))
            for s in specs[:25]
        ]
        super().__init__(placeholder="Спек…", options=options)
        self.game = game
        self.specs_by_id = {str(s.id): s for s in specs}

    async def callback(self, interaction: discord.Interaction) -> None:
        spec = self.specs_by_id[self.values[0]]
        await show_screen(
            interaction, content=f"Что сделать с **{spec.name}**?", embed=None, view=ClassActionView(self.game, spec)
        )


class _BackToClassButton(discord.ui.Button):
    def __init__(self, game, parent_cls):
        super().__init__(label="Назад к классу", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
        self.game = game
        self.parent_cls = parent_cls

    async def callback(self, interaction: discord.Interaction) -> None:
        await show_screen(
            interaction,
            content=f"Что сделать с **{self.parent_cls.name}**?",
            embed=None,
            view=ClassActionView(self.game, self.parent_cls),
        )
