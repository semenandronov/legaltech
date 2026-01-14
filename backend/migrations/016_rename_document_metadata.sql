-- Migration: Rename metadata column to document_metadata in documents table
-- This fixes SQLAlchemy reserved name conflict

-- Rename column if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'documents' 
        AND column_name = 'metadata'
    ) THEN
        ALTER TABLE documents RENAME COLUMN metadata TO document_metadata;
    END IF;
END $$;

-- Update comment
COMMENT ON COLUMN documents.document_metadata IS 'Additional metadata (tags, author, etc.) - renamed from metadata to avoid SQLAlchemy reserved name';

