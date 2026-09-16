import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class EventDraft:
    guild_id: int | None = None
    game_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    editing_raid_id: uuid.UUID | None = None

    name: str | None = None
    title: str | None = None
    description: str | None = None
    starts_at: datetime | None = None

    participant_limit: int = 0
    reminder_minutes: int = 30
    duration_minutes: int = 180

    channel_id: int | None = None
    mention_role_id: int | None = None

    banner_path: str | None = None
