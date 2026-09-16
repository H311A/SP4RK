from datetime import datetime

import pytz

from app.config import settings

DEFAULT_TZ = pytz.timezone(settings.timezone)


def resolve_timezone(tz_name: str | None) -> pytz.BaseTzInfo:
    if not tz_name:
        return DEFAULT_TZ
    try:
        return pytz.timezone(tz_name)
    except Exception:
        return DEFAULT_TZ


def parse_local_datetime(value: str, tz_name: str | None = None) -> datetime:
    naive = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    tz = resolve_timezone(tz_name)
    aware = tz.localize(naive)
    return aware.astimezone(pytz.utc).replace(tzinfo=None)


def discord_ts(dt: datetime, fmt: str = "F") -> str:
    unix = int(pytz.utc.localize(dt).timestamp())
    return f"<t:{unix}:{fmt}>"


def short_id(value) -> str:
    return str(value)[:8]
