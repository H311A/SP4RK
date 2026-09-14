from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    discord_token: str = os.getenv("DISCORD_TOKEN", "")
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://spark_user:spark_password@localhost:5432/spark_db")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    timezone: str = os.getenv("TIMEZONE", "Europe/Moscow")
    guild_name: str = os.getenv("GUILD_NAME", "Stormchasers")
    sync_commands: bool = _bool_env("SYNC_COMMANDS", True)
    debug: bool = _bool_env("DEBUG", False)
    log_file: str = os.getenv("LOG_FILE", "logs/sp4rk_errors.log")
    default_reminder_minutes: int = int(os.getenv("DEFAULT_REMINDER_MINUTES", "30"))
    ephemeral_delete_after: int = int(os.getenv("EPHEMERAL_DELETE_AFTER", "60"))
    bot_status: str = os.getenv("BOT_STATUS", "✨ Работаю вместо Джета.")


settings = Settings()
