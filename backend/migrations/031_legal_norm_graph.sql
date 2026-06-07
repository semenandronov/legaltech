-- Справочник (кодексы/НПА): граф норм и реестр article-level узлов.
-- PGVector (langchain_pg_embedding) хранит текст; эта схема — связи и стабильные ключи.

CREATE TABLE IF NOT EXISTS legal_norm_nodes (
    norm_node_key TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL,
    corpus_file_id TEXT,
    instrument_id TEXT NOT NULL,
    article_number TEXT NOT NULL,
    clause_ref TEXT NOT NULL DEFAULT '',
    full_path TEXT NOT NULL DEFAULT '',
    valid_from DATE,
    valid_to DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_legal_norm_nodes_instrument_article
    ON legal_norm_nodes(instrument_id, article_number);

CREATE INDEX IF NOT EXISTS idx_legal_norm_nodes_chunk_id
    ON legal_norm_nodes(chunk_id);

CREATE INDEX IF NOT EXISTS idx_legal_norm_nodes_corpus_file
    ON legal_norm_nodes(corpus_file_id);

CREATE INDEX IF NOT EXISTS idx_legal_norm_nodes_validity
    ON legal_norm_nodes(instrument_id, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS legal_norm_graph_edges (
    id TEXT PRIMARY KEY,
    source_norm_key TEXT NOT NULL REFERENCES legal_norm_nodes(norm_node_key) ON DELETE CASCADE,
    target_norm_key TEXT NOT NULL REFERENCES legal_norm_nodes(norm_node_key) ON DELETE CASCADE,
    edge_type TEXT NOT NULL CHECK (edge_type IN ('REFERENCES', 'FORWARD_TO', 'DEVELOPS', 'EXCEPTS')),
    source_ref_text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_norm_key, target_norm_key, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_legal_norm_edges_source_type
    ON legal_norm_graph_edges(source_norm_key, edge_type);

CREATE INDEX IF NOT EXISTS idx_legal_norm_edges_target
    ON legal_norm_graph_edges(target_norm_key);
