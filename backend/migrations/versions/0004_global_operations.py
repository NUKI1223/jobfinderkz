"""Keep shared paid-operation identity after the initiating administrator is deleted."""
from alembic import op

revision = '0004'
down_revision = '0003'


def upgrade():
    op.execute('CREATE TABLE global_operations (key varchar(128) PRIMARY KEY, job_id varchar(36) NOT NULL)')
    op.execute("""INSERT INTO global_operations (key, job_id)
        SELECT DISTINCT ON (payload->>'record_id', COALESCE(payload->>'version', '1'))
            'index:' || (payload->>'record_id') || ':' || COALESCE(payload->>'version', '1'), id
        FROM jobs WHERE kind='index_knowledge' AND payload ? 'record_id'
        ORDER BY payload->>'record_id', COALESCE(payload->>'version', '1'),
            CASE WHEN status='needs_review' THEN 0 WHEN status='running' THEN 1 ELSE 2 END, created_at""")


def downgrade():
    op.drop_table('global_operations')
