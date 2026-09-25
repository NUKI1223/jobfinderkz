"""Keep historic totals while adding auditable calculation details."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0002'
down_revision = '0001'


def upgrade():
    op.add_column('usage', sa.Column('details', JSONB(), nullable=False,
        server_default=sa.text("'{\"method\":\"legacy_unknown\"}'::jsonb")))


def downgrade():
    op.drop_column('usage', 'details')
