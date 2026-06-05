-- File-level summary index for hierarchical RAG (step 1 retrieval funnel).
-- Hybrid: pgvector embedding + PostgreSQL FTS on passport text.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS case_file_summaries (
    file_id TEXT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    filename TEXT NOT NULL DEFAULT '',
    doc_type TEXT,
    summary_text TEXT NOT NULL DEFAULT '',
    search_text TEXT NOT NULL DEFAULT '',
    fts_vector tsvector,
    embedding vector(256),
    content_hash VARCHAR(64),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_file_summaries_case_id
    ON case_file_summaries(case_id);

CREATE INDEX IF NOT EXISTS idx_case_file_summaries_fts
    ON case_file_summaries USING gin(fts_vector);

CREATE INDEX IF NOT EXISTS idx_case_file_summaries_embedding_hnsw
    ON case_file_summaries USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
