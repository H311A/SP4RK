import asyncio

import discord

from app.config import settings


class BannerUploadTimeout(Exception):
    pass


class BannerUploadCancelled(Exception):
    pass


class BannerUploadInvalid(Exception):
    pass


def banner_hint_text() -> str:
    ratio = round(settings.banner_width / settings.banner_height, 2)
    return (
        f"Пришли картинку для баннера сюда, в личные сообщения.\n\n"
        f"Рекомендуемый размер: {settings.banner_width}×{settings.banner_height} "
        f"(соотношение сторон примерно {ratio}:1). Можно прислать картинку другого размера "
        f"- я аккуратно обрежу или растяну её под нужный формат сам.\n"
        f"Формат: PNG или JPG, до {settings.banner_max_upload_mb} МБ.\n\n"
        f"Чтобы отменить загрузку, напиши \"отмена\"."
    )


def icon_hint_text() -> str:
    return (
        f"Пришли картинку для иконки класса сюда, в личные сообщения.\n\n"
        f"Картинка будет приведена к квадрату (по центру) и уменьшена до аккуратного размера "
        f"иконки. Прозрачный фон (PNG) поддерживается и сохранится.\n"
        f"Формат: PNG, JPG или GIF, до {settings.banner_max_upload_mb} МБ.\n\n"
        f"Чтобы пропустить и оставить обычный эмодзи, напиши \"отмена\"."
    )


async def collect_image_via_dm(bot: discord.Client, user: discord.abc.User, hint_text: str) -> bytes:
    try:
        dm_channel = user.dm_channel or await user.create_dm()
        await dm_channel.send(hint_text)
    except discord.Forbidden as exc:
        raise BannerUploadInvalid(
            "Не получилось написать тебе в личные сообщения. Разреши личные сообщения от "
            "участников сервера в настройках приватности Discord и попробуй снова."
        ) from exc

    def check(message: discord.Message) -> bool:
        return message.author.id == user.id and message.channel.id == dm_channel.id

    try:
        message = await bot.wait_for("message", check=check, timeout=settings.banner_upload_timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise BannerUploadTimeout() from exc

    if message.content.strip().lower() in {"отмена", "cancel"}:
        raise BannerUploadCancelled()

    if not message.attachments:
        raise BannerUploadInvalid("Нужно приложить именно картинку (PNG, JPG или GIF).")

    attachment = message.attachments[0]
    if attachment.size > settings.banner_max_upload_mb * 1024 * 1024:
        raise BannerUploadInvalid(f"Файл больше {settings.banner_max_upload_mb} МБ, пришли картинку полегче.")

    if not (attachment.content_type or "").startswith("image/"):
        raise BannerUploadInvalid("Это не похоже на картинку. Пришли PNG, JPG или GIF.")

    return await attachment.read()
