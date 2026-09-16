from dataclasses import dataclass, field
import os

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    discord_token: str = os.getenv("DISCORD_TOKEN", "")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://spark_user:spark_password@localhost:5432/spark_db"
    )
    timezone: str = os.getenv("TIMEZONE", "Europe/Moscow")
    guild_name: str = os.getenv("GUILD_NAME", "Stormchasers")
    sync_commands: bool = _bool_env("SYNC_COMMANDS", True)
    sync_guild_id: int | None = _optional_int_env("SYNC_GUILD_ID")
    debug: bool = _bool_env("DEBUG", False)
    log_file: str = os.getenv("LOG_FILE", "logs/sp4rk_errors.log")

    default_reminder_minutes: int = _int_env("DEFAULT_REMINDER_MINUTES", 30)
    default_event_duration_minutes: int = _int_env("DEFAULT_EVENT_DURATION_MINUTES", 180)
    ephemeral_delete_after: int = _int_env("EPHEMERAL_DELETE_AFTER", 60)
    menu_idle_timeout_seconds: int = _int_env("MENU_IDLE_TIMEOUT_SECONDS", 180)
    raid_purge_after_hours: int = _int_env("RAID_PURGE_AFTER_HOURS", 24)

    bot_status: str = os.getenv("BOT_STATUS", "✨ Записываем на события")

    banner_storage_dir: str = os.getenv("BANNER_STORAGE_DIR", "storage/banners")
    banner_width: int = _int_env("BANNER_WIDTH", 900)
    banner_height: int = _int_env("BANNER_HEIGHT", 260)
    banner_upload_timeout_seconds: int = _int_env("BANNER_UPLOAD_TIMEOUT_SECONDS", 120)
    banner_max_upload_mb: int = _int_env("BANNER_MAX_UPLOAD_MB", 15)

    brand_color: int = int(os.getenv("BRAND_COLOR", "0x000000"), 16)

    attendance_min_records_for_stats: int = _int_env("ATTENDANCE_MIN_RECORDS_FOR_STATS", 1)


settings = Settings()
