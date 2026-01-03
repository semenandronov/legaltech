-- Migration: Add case_id column to langchain_pg_embedding table for optimized filtering
-- This migration adds a dedicated case_id column and creates indexes for better performance

-- Add case_id column if it doesn't exist
ALTER TABLE langchain_pg_embedding 
ADD COLUMN IF NOT EXISTS case_id TEXT;

-- Fill case_id from JSONB metadata for existing records
UPDATE langchain_pg_embedding 
SET case_id = document->'metadata'->>'case_id'
WHERE case_id IS NULL AND document->'metadata'->>'case_id' IS NOT NULL;

-- Create B-tree index on case_id for fast filtering
CREATE INDEX IF NOT EXISTS idx_embeddings_case_id_btree 
ON langchain_pg_embedding(case_id);

-- Create expression index on doc_type for frequently used filtering
CREATE INDEX IF NOT EXISTS idx_embeddings_doc_type 
ON langchain_pg_embedding((document->'metadata'->>'doc_type'))
WHERE document->'metadata'->>'doc_type' IS NOT NULL;

