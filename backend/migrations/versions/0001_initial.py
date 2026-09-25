"""Initial schema: accounts, domain records, durable jobs, budgets and pgvector."""
from alembic import op
from pathlib import Path

revision = '0001'
down_revision = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    schema = Path(__file__).with_name('0001_schema.sql').read_text(encoding='utf-8')
    for statement in schema.split(';'):
        if statement.strip():
            op.execute(statement)
    op.execute("CREATE UNIQUE INDEX shared_dedup ON records (kind, dedup_key) WHERE owner_id IS NULL AND dedup_key IS NOT NULL")
    op.execute("CREATE INDEX knowledge_fts ON knowledge USING gin(to_tsvector('simple', text))")
    op.execute('CREATE INDEX knowledge_embedding ON knowledge USING hnsw (embedding vector_cosine_ops)')


def downgrade():
    for table in ['usage', 'knowledge', 'sessions', 'jobs', 'records', 'users', 'budgets']:
        op.drop_table(table)
