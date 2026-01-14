-- Migration: Add document editor tables for editable documents
-- Creates tables for storing documents created in the editor and their version history

-- Create documents table
CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR PRIMARY KEY,
    case_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    content_plain TEXT,
    document_metadata JSONB,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_documents_case FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    CONSTRAINT fk_documents_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_documents_case_id ON documents(case_id);
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC);

-- Create document_versions table for version history
CREATE TABLE IF NOT EXISTS document_versions (
    id VARCHAR PRIMARY KEY,
    document_id VARCHAR NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    CONSTRAINT fk_document_versions_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    CONSTRAINT fk_document_versions_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

-- Create indexes for document_versions
CREATE INDEX IF NOT EXISTS idx_document_versions_document_id ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_document_versions_version ON document_versions(document_id, version DESC);

-- Add comments for documentation
COMMENT ON TABLE documents IS 'Editable documents created in the document editor';
COMMENT ON COLUMN documents.content IS 'HTML content from TipTap editor';
COMMENT ON COLUMN documents.content_plain IS 'Plain text version for search purposes';
COMMENT ON COLUMN documents.document_metadata IS 'Additional metadata (tags, author, etc.)';
COMMENT ON TABLE document_versions IS 'Version history of documents for tracking changes';

