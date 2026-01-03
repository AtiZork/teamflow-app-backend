"""add attendance columns

Revision ID: 20251210_add_attendance_columns
Revises: 
Create Date: 2025-12-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251210_add_attendance_columns'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add each column with IF NOT EXISTS to be idempotent
    op.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS productive_hours VARCHAR(10);")
    op.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS break_time VARCHAR(10);")
    op.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS total_minutes INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS productive_minutes INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS overtime_minutes INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS year INTEGER;")
    op.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS month INTEGER;")
    op.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS week_number INTEGER;")
    op.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS day_of_week INTEGER;")


def downgrade() -> None:
    # Remove columns if they exist
    op.execute("ALTER TABLE attendance DROP COLUMN IF EXISTS productive_hours;")
    op.execute("ALTER TABLE attendance DROP COLUMN IF EXISTS break_time;")
    op.execute("ALTER TABLE attendance DROP COLUMN IF EXISTS total_minutes;")
    op.execute("ALTER TABLE attendance DROP COLUMN IF EXISTS productive_minutes;")
    op.execute("ALTER TABLE attendance DROP COLUMN IF EXISTS overtime_minutes;")
    op.execute("ALTER TABLE attendance DROP COLUMN IF EXISTS year;")
    op.execute("ALTER TABLE attendance DROP COLUMN IF EXISTS month;")
    op.execute("ALTER TABLE attendance DROP COLUMN IF EXISTS week_number;")
    op.execute("ALTER TABLE attendance DROP COLUMN IF EXISTS day_of_week;")
