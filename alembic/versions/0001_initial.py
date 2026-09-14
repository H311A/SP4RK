"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "raid_classes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("icon", sa.String(length=120), nullable=False),
        sa.Column("limit_count", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "name", name="uq_class_guild_name"),
    )
    op.create_index(op.f("ix_raid_classes_guild_id"), "raid_classes", ["guild_id"])
    op.create_table(
        "raids",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("reminder_minutes", sa.Integer(), nullable=False),
        sa.Column("mention_role_id", sa.BigInteger(), nullable=True),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_raids_guild_id"), "raids", ["guild_id"])
    op.create_index(op.f("ix_raids_starts_at"), "raids", ["starts_at"])
    op.create_table(
        "raid_signups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raid_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["raid_classes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raid_id", "user_id", name="uq_signup_raid_user"),
    )
    op.create_index(op.f("ix_raid_signups_raid_id"), "raid_signups", ["raid_id"])
    op.create_index(op.f("ix_raid_signups_user_id"), "raid_signups", ["user_id"])
    op.create_table(
        "reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raid_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("minutes_before", sa.Integer(), nullable=False),
        sa.Column("sent", sa.Boolean(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reminders_raid_id"), "reminders", ["raid_id"])

def downgrade() -> None:
    op.drop_index(op.f("ix_reminders_raid_id"), table_name="reminders")
    op.drop_table("reminders")
    op.drop_index(op.f("ix_raid_signups_user_id"), table_name="raid_signups")
    op.drop_index(op.f("ix_raid_signups_raid_id"), table_name="raid_signups")
    op.drop_table("raid_signups")
    op.drop_index(op.f("ix_raids_starts_at"), table_name="raids")
    op.drop_index(op.f("ix_raids_guild_id"), table_name="raids")
    op.drop_table("raids")
    op.drop_index(op.f("ix_raid_classes_guild_id"), table_name="raid_classes")
    op.drop_table("raid_classes")
    op.drop_table("guilds")
