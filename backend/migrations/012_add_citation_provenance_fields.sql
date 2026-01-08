-- Migration: Add citation provenance fields to document_chunks table
-- Phase 1: Provenance Completeness
-- Adds char_start, char_end, doc_id, source_url, trust_score fields for citation system

-- Add char_start column (nullable for backward compatibility)
ALTER TABLE document_chunks 
ADD COLUMN IF NOT EXISTS char_start INTEGER;

-- Add char_end column (nullable for backward compatibility)
ALTER TABLE document_chunks 
ADD COLUMN IF NOT EXISTS char_end INTEGER;

-- Add doc_id column (nullable for backward compatibility, indexed for performance)
ALTER TABLE document_chunks 
ADD COLUMN IF NOT EXISTS doc_id VARCHAR;

CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_id ON document_chunks(doc_id);

-- Add source_url column (nullable for backward compatibility)
ALTER TABLE document_chunks 
ADD COLUMN IF NOT EXISTS source_url VARCHAR;

-- Add trust_score column (nullable for backward compatibility)
ALTER TABLE document_chunks 
ADD COLUMN IF NOT EXISTS trust_score FLOAT;

-- Add comment to table
COMMENT ON COLUMN document_chunks.char_start IS 'Начальная позиция символа в исходном документе для точного цитирования';
COMMENT ON COLUMN document_chunks.char_end IS 'Конечная позиция символа в исходном документе для точного цитирования';
COMMENT ON COLUMN document_chunks.doc_id IS 'Уникальный ID документа для deep links и точного цитирования';
COMMENT ON COLUMN document_chunks.source_url IS 'URL для внешних источников (если применимо)';
COMMENT ON COLUMN document_chunks.trust_score IS 'Доверенность источника (0.0-1.0)';


