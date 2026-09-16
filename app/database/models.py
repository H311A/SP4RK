import uuid
from datetime import datetime, timedelta

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Guild(Base):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class GuildAdminRole(Base):
    __tablename__ = "guild_admin_roles"
    __table_args__ = (UniqueConstraint("guild_id", "role_id", name="uq_guild_admin_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_name: Mapped[str] = mapped_column(String(120), nullable=False)
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_game_guild_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str] = mapped_column(String(120), nullable=False, default="\U0001F3AE")
    color: Mapped[int] = mapped_column(Integer, nullable=False, default=0x5865F2)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    classes: Mapped[list["GameClass"]] = relationship(back_populates="game", cascade="all, delete-orphan")


class GameClass(Base):
    __tablename__ = "game_classes"
    __table_args__ = (UniqueConstraint("game_id", "name", name="uq_class_game_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), index=True)
    parent_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_classes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role: Mapped[str | None] = mapped_column(String(10), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str] = mapped_column(String(120), nullable=False, default="⚡")
    icon_emoji_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    icon_emoji_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    limit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    game: Mapped[Game] = relationship(back_populates="classes")


class RaidTemplate(Base):
    __tablename__ = "raid_templates"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_template_guild_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mention_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reminder_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    participant_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=180)

    banner_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    banner_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    banner_height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recurrence_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recurrence_day_of_week: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    recurrence_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    recurrence_lead_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_recurrence_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    game: Mapped[Game] = relationship()


class Raid(Base):
    __tablename__ = "raids"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raid_templates.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reminder_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    mention_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    participant_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    banner_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discord_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    registration_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    signups: Mapped[list["RaidSignup"]] = relationship(back_populates="raid", cascade="all, delete-orphan")
    reminders: Mapped[list["Reminder"]] = relationship(back_populates="raid", cascade="all, delete-orphan")
    game: Mapped[Game] = relationship()

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes or 0)


class RaidSignup(Base):
    __tablename__ = "raid_signups"
    __table_args__ = (UniqueConstraint("raid_id", "user_id", name="uq_signup_raid_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raid_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("raids.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_classes.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="accepted")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    raid: Mapped[Raid] = relationship(back_populates="signups")
    raid_class: Mapped[GameClass | None] = relationship()


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raid_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("raids.id", ondelete="CASCADE"), index=True)
    minutes_before: Mapped[int] = mapped_column(Integer, nullable=False)
    sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    raid: Mapped[Raid] = relationship(back_populates="reminders")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), index=True)
    game_name: Mapped[str] = mapped_column(String(100), nullable=False)
    raid_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    raid_title: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    class_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    final_status: Mapped[str] = mapped_column(String(20), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
