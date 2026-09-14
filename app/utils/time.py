from datetime import datetime
import pytz

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

def parse_moscow_datetime(value: str) -> datetime:
    naive = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    aware = MOSCOW_TZ.localize(naive)
    # В БД храним UTC без tzinfo, чтобы не смешивать aware/naive.
    return aware.astimezone(pytz.utc).replace(tzinfo=None)

def discord_ts(dt: datetime, fmt: str = "F") -> str:
    unix = int(pytz.utc.localize(dt).timestamp())
    return f"<t:{unix}:{fmt}>"

def short_id(value) -> str:
    return str(value)[:8]
