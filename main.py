import asyncio

from app.bot.client import SparkBot, setup_logging
from app.bot.ephemeral import install_ephemeral_autodelete_patch
from app.config import settings

install_ephemeral_autodelete_patch()
setup_logging()


async def main() -> None:
    if not settings.discord_token:
        raise RuntimeError("Заполни DISCORD_TOKEN в .env")
    bot = SparkBot()
    await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
