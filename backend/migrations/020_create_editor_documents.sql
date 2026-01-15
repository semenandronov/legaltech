-- Migration: Create editor_documents table for document editor
-- This is separate from the existing 'documents' table which is used for uploaded files

-- Create editor_documents table
CREATE TABLE IF NOT EXISTS editor_documents (
    id VARCHAR PRIMARY KEY,
    case_id VARCHAR NOT NULL,
    "userId" VARCHAR NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    content_plain TEXT,
    document_metadata JSONB,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_editor_documents_case FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    CONSTRAINT fk_editor_documents_user FOREIGN KEY ("userId") REFERENCES users(id) ON DELETE CASCADE
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_editor_documents_case_id ON editor_documents(case_id);
CREATE INDEX IF NOT EXISTS idx_editor_documents_user_id ON editor_documents("userId");
CREATE INDEX IF NOT EXISTS idx_editor_documents_created_at ON editor_documents(created_at DESC);

-- Create editor_document_versions table for version history
CREATE TABLE IF NOT EXISTS editor_document_versions (
    id VARCHAR PRIMARY KEY,
    document_id VARCHAR NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR,
    CONSTRAINT fk_editor_document_versions_document FOREIGN KEY (document_id) REFERENCES editor_documents(id) ON DELETE CASCADE,
    CONSTRAINT fk_editor_document_versions_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

-- Create indexes for editor_document_versions
CREATE INDEX IF NOT EXISTS idx_editor_document_versions_document_id ON editor_document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_editor_document_versions_version ON editor_document_versions(document_id, version DESC);

-- Add comments for documentation
COMMENT ON TABLE editor_documents IS 'Editable documents created in the document editor';
COMMENT ON COLUMN editor_documents.content IS 'HTML content from TipTap editor';
COMMENT ON COLUMN editor_documents.content_plain IS 'Plain text version for search purposes';
COMMENT ON COLUMN editor_documents.document_metadata IS 'Additional metadata (tags, author, etc.)';
COMMENT ON TABLE editor_document_versions IS 'Version history of editor documents for tracking changes';

