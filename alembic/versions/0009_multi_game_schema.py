"""multi-game schema: games, game_classes, banners, recurrence, attendance

Revision ID: 0009_multi_game_schema
Revises: 0008_template_names_text
Create Date: 2026-09-15
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0009_multi_game_schema"
down_revision = "0008_template_names_text"
branch_labels = None
depends_on = None

DEFAULT_GAME_NAME = "Where Winds Meet"
DEFAULT_GAME_ICON = "\U0001F32C️"
SECONDARY_GAME_NAME = "World of Warcraft: Forever"
SECONDARY_GAME_ICON = "⚔️"
BRAND_COLOR = 0x5865F2


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "games",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(120), nullable=False, server_default="\U0001F3AE"),
        sa.Column("color", sa.Integer, nullable=False, server_default=str(BRAND_COLOR)),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "name", name="uq_game_guild_name"),
    )

    op.create_table(
        "game_classes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("game_id", UUID(as_uuid=True), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(120), nullable=False, server_default="⚡"),
        sa.Column("limit_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("game_id", "name", name="uq_class_game_name"),
    )

    op.create_table(
        "attendance_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("game_name", sa.String(100), nullable=False),
        sa.Column("raid_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("raid_title", sa.Text, nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("class_name", sa.String(100), nullable=True),
        sa.Column("final_status", sa.String(20), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.add_column("raid_templates", sa.Column("game_id", UUID(as_uuid=True), nullable=True))
    op.add_column("raid_templates", sa.Column("duration_minutes", sa.Integer, nullable=False, server_default="180"))
    op.add_column("raid_templates", sa.Column("banner_path", sa.String(255), nullable=True))
    op.add_column("raid_templates", sa.Column("banner_width", sa.Integer, nullable=True))
    op.add_column("raid_templates", sa.Column("banner_height", sa.Integer, nullable=True))
    op.add_column("raid_templates", sa.Column("recurrence_enabled", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("raid_templates", sa.Column("recurrence_day_of_week", sa.SmallInteger, nullable=True))
    op.add_column("raid_templates", sa.Column("recurrence_time", sa.String(5), nullable=True))
    op.add_column("raid_templates", sa.Column("recurrence_lead_days", sa.Integer, nullable=False, server_default="3"))
    op.add_column("raid_templates", sa.Column("last_recurrence_run", sa.DateTime(), nullable=True))

    op.add_column("raids", sa.Column("game_id", UUID(as_uuid=True), nullable=True))
    op.add_column("raids", sa.Column("template_id", UUID(as_uuid=True), nullable=True))
    op.add_column("raids", sa.Column("duration_minutes", sa.Integer, nullable=False, server_default="180"))
    op.add_column("raids", sa.Column("banner_path", sa.String(255), nullable=True))
    op.add_column("raids", sa.Column("discord_event_id", sa.BigInteger, nullable=True))
    op.add_column("raids", sa.Column("registration_closed", sa.Boolean, nullable=False, server_default=sa.false()))

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    has_raid_classes = "raid_classes" in existing_tables

    guild_rows = bind.execute(sa.text("SELECT id FROM guilds")).fetchall()

    for (guild_id,) in guild_rows:
        default_game_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO games (id, guild_id, name, icon, color, sort_order, is_active, created_by, created_at) "
                "VALUES (:id, :guild_id, :name, :icon, :color, 0, TRUE, 0, now())"
            ),
            {
                "id": default_game_id,
                "guild_id": guild_id,
                "name": DEFAULT_GAME_NAME,
                "icon": DEFAULT_GAME_ICON,
                "color": BRAND_COLOR,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO games (id, guild_id, name, icon, color, sort_order, is_active, created_by, created_at) "
                "VALUES (:id, :guild_id, :name, :icon, :color, 1, TRUE, 0, now())"
            ),
            {
                "id": uuid.uuid4(),
                "guild_id": guild_id,
                "name": SECONDARY_GAME_NAME,
                "icon": SECONDARY_GAME_ICON,
                "color": BRAND_COLOR,
            },
        )

        if has_raid_classes:
            classes = bind.execute(
                sa.text(
                    "SELECT id, name, icon, limit_count, sort_order, is_active, created_by, created_at "
                    "FROM raid_classes WHERE guild_id = :guild_id"
                ),
                {"guild_id": guild_id},
            ).fetchall()
            for row in classes:
                bind.execute(
                    sa.text(
                        "INSERT INTO game_classes "
                        "(id, game_id, name, icon, limit_count, sort_order, is_active, created_by, created_at) "
                        "VALUES (:id, :game_id, :name, :icon, :limit_count, :sort_order, :is_active, :created_by, :created_at)"
                    ),
                    {
                        "id": row.id,
                        "game_id": default_game_id,
                        "name": row.name,
                        "icon": row.icon,
                        "limit_count": row.limit_count,
                        "sort_order": row.sort_order,
                        "is_active": row.is_active,
                        "created_by": row.created_by,
                        "created_at": row.created_at,
                    },
                )

        bind.execute(
            sa.text("UPDATE raids SET game_id = :gid WHERE guild_id = :guild_id"),
            {"gid": default_game_id, "guild_id": guild_id},
        )
        bind.execute(
            sa.text("UPDATE raid_templates SET game_id = :gid WHERE guild_id = :guild_id"),
            {"gid": default_game_id, "guild_id": guild_id},
        )

    op.alter_column("raids", "game_id", nullable=False)
    op.alter_column("raid_templates", "game_id", nullable=False)

    op.create_foreign_key("fk_raids_game", "raids", "games", ["game_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_raids_template", "raids", "raid_templates", ["template_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_raid_templates_game", "raid_templates", "games", ["game_id"], ["id"], ondelete="CASCADE")

    if has_raid_classes:
        for fk in inspector.get_foreign_keys("raid_signups"):
            if fk["constrained_columns"] == ["class_id"]:
                op.drop_constraint(fk["name"], "raid_signups", type_="foreignkey")
        op.create_foreign_key(
            "fk_raid_signups_class", "raid_signups", "game_classes", ["class_id"], ["id"], ondelete="SET NULL"
        )
        op.drop_table("raid_classes")


def downgrade() -> None:
    pass
