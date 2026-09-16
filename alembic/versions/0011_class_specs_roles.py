"""class specs and roles

Revision ID: 0011_class_specs_roles
Revises: 0010_class_icon_emoji
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0011_class_specs_roles"
down_revision = "0010_class_icon_emoji"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_classes",
        sa.Column("parent_class_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column("game_classes", sa.Column("role", sa.String(10), nullable=True))
    op.create_foreign_key(
        "fk_game_classes_parent_class_id",
        "game_classes",
        "game_classes",
        ["parent_class_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_game_classes_parent_class_id", "game_classes", ["parent_class_id"])


def downgrade() -> None:
    pass
