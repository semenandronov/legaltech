-- Migration: Add LangGraph Store table for long-term memory and pattern storage
-- This table stores patterns, precedents, and successful plans for reuse across cases

CREATE TABLE IF NOT EXISTS langgraph_store (
    id SERIAL PRIMARY KEY,
    namespace VARCHAR(255) NOT NULL,
    key VARCHAR(500) NOT NULL,
    value JSONB NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(namespace, key)
);

-- Indexes for fast search
CREATE INDEX IF NOT EXISTS idx_store_namespace ON langgraph_store(namespace);
CREATE INDEX IF NOT EXISTS idx_store_key ON langgraph_store(key);

-- GIN index for JSONB value search
CREATE INDEX IF NOT EXISTS idx_store_value_gin ON langgraph_store USING GIN(value);

-- Index for metadata search
CREATE INDEX IF NOT EXISTS idx_store_metadata_gin ON langgraph_store USING GIN(metadata) WHERE metadata IS NOT NULL;

-- Index for time-based queries
CREATE INDEX IF NOT EXISTS idx_store_updated_at ON langgraph_store(updated_at DESC);

COMMENT ON TABLE langgraph_store IS 'Stores patterns, precedents, and successful plans for reuse across legal cases';
COMMENT ON COLUMN langgraph_store.namespace IS 'Namespace for grouping patterns (e.g., risk_patterns/employment_contract)';
COMMENT ON COLUMN langgraph_store.key IS 'Unique key for the pattern (e.g., Missing non-compete clause)';
COMMENT ON COLUMN langgraph_store.value IS 'Pattern value stored as JSONB';
COMMENT ON COLUMN langgraph_store.metadata IS 'Additional metadata (case_id, saved_at, source, etc.)';

