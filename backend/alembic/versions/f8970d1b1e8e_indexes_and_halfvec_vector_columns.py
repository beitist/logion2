"""indexes and halfvec vector columns

Revision ID: f8970d1b1e8e
Revises: 
Create Date: 2026-06-09 23:38:22.452296

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8970d1b1e8e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _convert_to_halfvec(table: str) -> None:
    """Convert <table>.embedding from vector(2048) -> halfvec(2048), only if
    it is still a plain vector (idempotent / safe on fresh halfvec DBs)."""
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_type  t ON t.oid = a.atttypid
            WHERE c.relname = '{table}' AND a.attname = 'embedding' AND t.typname = 'vector'
          ) THEN
            ALTER TABLE {table}
              ALTER COLUMN embedding TYPE halfvec(2048) USING embedding::halfvec(2048);
          END IF;
        END $$;
        """
    )


def upgrade() -> None:
    """Add missing btree indexes, convert embeddings to halfvec, add HNSW indexes."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- btree indexes (hot query paths) ---
    op.execute("CREATE INDEX IF NOT EXISTS ix_segments_project_id ON segments (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_segments_project_index ON segments (project_id, index)")

    # --- halfvec conversion (vector(2048) exceeds pgvector's 2000-dim HNSW limit;
    #     halfvec supports up to 4000 dims and is fp16 — negligible loss for cosine) ---
    _convert_to_halfvec("segments")
    _convert_to_halfvec("context_chunks")

    # --- ANN indexes (HNSW, cosine) ---
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_segments_embedding_hnsw "
        "ON segments USING hnsw (embedding halfvec_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_context_chunks_embedding_hnsw "
        "ON context_chunks USING hnsw (embedding halfvec_cosine_ops)"
    )


def downgrade() -> None:
    """Reverse the migration (precision lost in halfvec conversion is not recovered)."""
    op.execute("DROP INDEX IF EXISTS ix_context_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_segments_embedding_hnsw")

    op.execute("ALTER TABLE context_chunks ALTER COLUMN embedding TYPE vector(2048) USING embedding::vector(2048)")
    op.execute("ALTER TABLE segments ALTER COLUMN embedding TYPE vector(2048) USING embedding::vector(2048)")

    op.execute("DROP INDEX IF EXISTS ix_segments_project_index")
    op.execute("DROP INDEX IF EXISTS ix_segments_project_id")
