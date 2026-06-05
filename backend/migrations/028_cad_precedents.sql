-- Судебная практика (КАД): отдельное хранилище с EmbeddingsGigaR (2560) + FTS.
-- Не смешивать с langchain_pg_embedding (дела пользователей, vector 256).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS cad_precedent_documents (
    id TEXT PRIMARY KEY,
    source_row_id TEXT,
    case_number TEXT NOT NULL DEFAULT '',
    cad_case_number TEXT,
    court_name TEXT,
    court_tier TEXT,
    judgment_date DATE,
    act_kind TEXT,
    outcome_summary TEXT,
    raw_text TEXT,
    batch_id TEXT,
    created_by_user_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cad_precedent_documents_case_number
    ON cad_precedent_documents(case_number);

CREATE INDEX IF NOT EXISTS idx_cad_precedent_documents_batch_id
    ON cad_precedent_documents(batch_id);

CREATE TABLE IF NOT EXISTS cad_precedent_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES cad_precedent_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    chunk_text TEXT NOT NULL,
    embedding vector(2560),
    fts_vector tsvector,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cad_precedent_chunks_document_id
    ON cad_precedent_chunks(document_id);

CREATE INDEX IF NOT EXISTS idx_cad_precedent_chunks_fts
    ON cad_precedent_chunks USING gin(fts_vector);

-- HNSW для vector(2560) на Neon/pgvector недоступен (лимит 2000 измерений).
-- Векторный поиск: exact scan (<=>); для пилота (~10k фрагментов) достаточно.
-- ANN-индекс при необходимости создаётся в court_practice_store.ensure_schema() при dim<=2000.
