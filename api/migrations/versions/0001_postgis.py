"""Establish the PostGIS prerequisite without creating speculative business tables."""

from alembic import op

revision = "0001_postgis"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    """Keep PostGIS and its data; Alembic rolls back only the revision marker."""
