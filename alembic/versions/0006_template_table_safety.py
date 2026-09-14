"""ensure templates table exists

Revision ID: 0006_tmpl_safe
Revises: 0005_tmpl
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_tmpl_safe"
down_revision = "0005_tmpl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "raid_templates" not in tables:
        op.create_table(
            "raid_templates",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("guild_id", sa.BigInteger(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("channel_id", sa.BigInteger(), nullable=False),
            sa.Column("mention_role_id", sa.BigInteger(), nullable=True),
            sa.Column("reminder_minutes", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("participant_limit", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("guild_id", "name", name="uq_template_guild_name"),
        )
        op.create_index(op.f("ix_raid_templates_guild_id"), "raid_templates", ["guild_id"])
        return

    columns = {column["name"] for column in inspector.get_columns("raid_templates")}
    with op.batch_alter_table("raid_templates") as batch_op:
        if "participant_limit" not in columns:
            batch_op.add_column(sa.Column("participant_limit", sa.Integer(), nullable=False, server_default="1"))
        if "reminder_minutes" not in columns:
            batch_op.add_column(sa.Column("reminder_minutes", sa.Integer(), nullable=False, server_default="30"))
        if "mention_role_id" not in columns:
            batch_op.add_column(sa.Column("mention_role_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    pass
