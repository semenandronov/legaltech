-- Migration: Add LangGraph Store table for long-term memory
-- This table stores key-value data for memory profiles, case memory,
-- query history, and insights.

-- Create the langgraph_store table
CREATE TABLE IF NOT EXISTS langgraph_store (
    key VARCHAR(500) PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Create indexes for efficient lookups
CREATE INDEX IF NOT EXISTS ix_langgraph_store_key ON langgraph_store (key);
CREATE INDEX IF NOT EXISTS ix_langgraph_store_updated_at ON langgraph_store (updated_at);

-- Add comment
COMMENT ON TABLE langgraph_store IS 'LangGraph Store for agent long-term memory (profiles, case memory, query history, insights)';
COMMENT ON COLUMN langgraph_store.key IS 'Key in format namespace/id (e.g., user_profile/user-123)';
COMMENT ON COLUMN langgraph_store.value IS 'JSON-encoded value';

