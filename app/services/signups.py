import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Raid, RaidSignup
from app.repositories.classes import list_classes
from app.repositories.raids import get_raid
from app.repositories.signups import delete_signup, get_signup, list_backups_ordered, upsert_signup


def _accepted_count_for_class(raid: Raid, class_id, exclude_user_id: int | None = None) -> int:
    return sum(
        1
        for s in raid.signups
        if s.status == "accepted" and s.class_id == class_id and s.user_id != exclude_user_id
    )


def _accepted_total(raid: Raid, exclude_user_id: int | None = None) -> int:
    return sum(1 for s in raid.signups if s.status == "accepted" and s.user_id != exclude_user_id)


def class_has_room(raid: Raid, cls, exclude_user_id: int | None = None) -> bool:
    if not cls or not cls.limit_count:
        return True
    return _accepted_count_for_class(raid, cls.id, exclude_user_id) < cls.limit_count


def raid_has_room(raid: Raid, exclude_user_id: int | None = None) -> bool:
    if not raid.participant_limit:
        return True
    return _accepted_total(raid, exclude_user_id) < raid.participant_limit


async def join_best_effort(session: AsyncSession, raid: Raid, cls, user_id: int, display_name: str) -> str:
    has_class_room = class_has_room(raid, cls, exclude_user_id=user_id)
    has_total_room = raid_has_room(raid, exclude_user_id=user_id)
    final_status = "accepted" if (has_class_room and has_total_room) else "backup"
    await upsert_signup(session, raid.id, user_id, display_name, cls.id if cls else None, final_status)
    return final_status


async def join_as_backup(session: AsyncSession, raid: Raid, cls, user_id: int, display_name: str) -> None:
    await upsert_signup(session, raid.id, user_id, display_name, cls.id if cls else None, "backup")


async def set_maybe(session: AsyncSession, raid: Raid, cls, user_id: int, display_name: str) -> None:
    await upsert_signup(session, raid.id, user_id, display_name, cls.id if cls else None, "maybe")


async def get_backup_position(session: AsyncSession, raid_id: uuid.UUID, user_id: int) -> int | None:
    ordered = await list_backups_ordered(session, raid_id)
    for i, signup in enumerate(ordered, start=1):
        if signup.user_id == user_id:
            return i
    return None


async def set_declined(session: AsyncSession, raid: Raid, user_id: int, display_name: str) -> None:
    await upsert_signup(session, raid.id, user_id, display_name, None, "declined")


async def toggle_notifications(session: AsyncSession, signup: RaidSignup) -> bool:
    signup.notifications_enabled = not signup.notifications_enabled
    return signup.notifications_enabled


async def leave_and_promote(
    session: AsyncSession, raid_id: uuid.UUID, signup: RaidSignup
) -> RaidSignup | None:
    was_accepted = signup.status == "accepted"
    left_class_id = signup.class_id
    await delete_signup(session, signup)
    await session.flush()

    if not was_accepted:
        return None

    fresh_raid = await get_raid(session, raid_id)
    if fresh_raid is None:
        return None

    backups = sorted(
        (s for s in fresh_raid.signups if s.status == "backup"),
        key=lambda s: s.joined_at or datetime.min,
    )
    classes = {c.id: c for c in await list_classes(session, fresh_raid.game_id, active_only=False)}

    def is_eligible(candidate: RaidSignup) -> bool:
        cls = classes.get(candidate.class_id) if candidate.class_id else None
        return class_has_room(fresh_raid, cls, exclude_user_id=candidate.user_id) and raid_has_room(
            fresh_raid, exclude_user_id=candidate.user_id
        )

    left_role = classes[left_class_id].role if left_class_id and left_class_id in classes else None

    if left_role is not None:
        for candidate in backups:
            cls = classes.get(candidate.class_id) if candidate.class_id else None
            candidate_role = cls.role if cls else None
            if candidate_role == left_role and is_eligible(candidate):
                candidate.status = "accepted"
                await session.flush()
                return candidate

    for candidate in backups:
        if is_eligible(candidate):
            candidate.status = "accepted"
            await session.flush()
            return candidate

    return None
