"""Retain sub-micro-dollar embedding costs rather than rounding them to zero."""
from alembic import op

revision = '0003'
down_revision = '0002'


def upgrade():
    op.execute('ALTER TABLE budgets ALTER COLUMN charged TYPE numeric(14,9)')
    op.execute('ALTER TABLE usage ALTER COLUMN reserved TYPE numeric(14,9)')
    op.execute('ALTER TABLE usage ALTER COLUMN actual TYPE numeric(14,9)')


def downgrade():
    op.execute('ALTER TABLE budgets ALTER COLUMN charged TYPE numeric(12,6)')
    op.execute('ALTER TABLE usage ALTER COLUMN reserved TYPE numeric(12,6)')
    op.execute('ALTER TABLE usage ALTER COLUMN actual TYPE numeric(12,6)')
