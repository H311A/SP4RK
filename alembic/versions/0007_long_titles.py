"""allow long emoji titles

Revision ID: 0007_long_titles
Revises: 0006_tmpl_safe
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_long_titles"
down_revision = "0006_tmpl_safe"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "raids") and _has_column(inspector, "raids", "title"):
        op.execute("ALTER TABLE raids ALTER COLUMN title TYPE TEXT")

    if _has_table(inspector, "raid_templates") and _has_column(inspector, "raid_templates", "title"):
        op.execute("ALTER TABLE raid_templates ALTER COLUMN title TYPE TEXT")


def downgrade() -> None:
    # Не сужаем обратно до VARCHAR, чтобы не потерять длинные emoji-названия.
    pass
