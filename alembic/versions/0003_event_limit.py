"""event participant limit

Revision ID: 0003_event_limit
Revises: 0002_admin_roles_notifications_lifecycle
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_event_limit"
down_revision = "0002_admin_roles_notifications_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    raid_columns = {column["name"] for column in inspector.get_columns("raids")}
    if "participant_limit" not in raid_columns:
        op.add_column(
            "raids",
            sa.Column("participant_limit", sa.Integer(), nullable=False, server_default="0"),
        )
        op.alter_column("raids", "participant_limit", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    raid_columns = {column["name"] for column in inspector.get_columns("raids")}
    if "participant_limit" in raid_columns:
        op.drop_column("raids", "participant_limit")
