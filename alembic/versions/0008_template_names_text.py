"""allow long emoji template names

Revision ID: 0008_template_names_text
Revises: 0007_long_titles
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_template_names_text"
down_revision = "0007_long_titles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "raid_templates" in set(inspector.get_table_names()):
        columns = {column["name"] for column in inspector.get_columns("raid_templates")}
        if "name" in columns:
            op.execute("ALTER TABLE raid_templates ALTER COLUMN name TYPE TEXT")
        if "title" in columns:
            op.execute("ALTER TABLE raid_templates ALTER COLUMN title TYPE TEXT")
    if "raids" in set(inspector.get_table_names()):
        columns = {column["name"] for column in inspector.get_columns("raids")}
        if "title" in columns:
            op.execute("ALTER TABLE raids ALTER COLUMN title TYPE TEXT")


def downgrade() -> None:
    pass
