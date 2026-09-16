"""class icons backed by application emoji

Revision ID: 0010_class_icon_emoji
Revises: 0009_multi_game_schema
Create Date: 2026-09-15
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_class_icon_emoji"
down_revision = "0009_multi_game_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_classes", sa.Column("icon_emoji_id", sa.BigInteger(), nullable=True))
    op.add_column("game_classes", sa.Column("icon_emoji_name", sa.String(32), nullable=True))


def downgrade() -> None:
    pass
