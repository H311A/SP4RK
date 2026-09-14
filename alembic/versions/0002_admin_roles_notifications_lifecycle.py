"""admin roles, notification toggle and lifecycle tweaks

Revision ID: 0002_admin_roles_notifications_lifecycle
Revises: 0001_initial
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_admin_roles_notifications_lifecycle"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guild_admin_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("role_name", sa.String(length=120), nullable=False),
        sa.Column("added_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "role_id", name="uq_guild_admin_role"),
    )
    op.create_index(op.f("ix_guild_admin_roles_guild_id"), "guild_admin_roles", ["guild_id"])

    op.add_column(
        "raid_signups",
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.alter_column("raid_signups", "notifications_enabled", server_default=None)

    # Поле уже могло быть добавлено вручную в одной из тестовых версий.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    raid_columns = {column["name"] for column in inspector.get_columns("raids")}
    if "mention_role_id" not in raid_columns:
        op.add_column("raids", sa.Column("mention_role_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    signup_columns = {column["name"] for column in inspector.get_columns("raid_signups")}
    if "notifications_enabled" in signup_columns:
        op.drop_column("raid_signups", "notifications_enabled")

    op.drop_index(op.f("ix_guild_admin_roles_guild_id"), table_name="guild_admin_roles")
    op.drop_table("guild_admin_roles")
