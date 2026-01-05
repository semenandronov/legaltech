-- Migration: Add cell_comments table
-- Created: 2024-07-XX
-- Description: Stores comments on tabular cells for collaborative review

CREATE TABLE IF NOT EXISTS cell_comments (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tabular_review_id VARCHAR NOT NULL,
    file_id VARCHAR NOT NULL,
    column_id VARCHAR NOT NULL,
    comment_text TEXT NOT NULL,
    created_by VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_resolved BOOLEAN DEFAULT false,
    resolved_at TIMESTAMP,
    resolved_by VARCHAR,
    
    CONSTRAINT fk_cell_comments_review FOREIGN KEY (tabular_review_id) REFERENCES tabular_reviews(id) ON DELETE CASCADE,
    CONSTRAINT fk_cell_comments_file FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    CONSTRAINT fk_cell_comments_column FOREIGN KEY (column_id) REFERENCES tabular_columns(id) ON DELETE CASCADE,
    CONSTRAINT fk_cell_comments_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_cell_comments_resolved_by FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_cell_comments_review_id ON cell_comments(tabular_review_id);
CREATE INDEX IF NOT EXISTS idx_cell_comments_file_id ON cell_comments(file_id);
CREATE INDEX IF NOT EXISTS idx_cell_comments_column_id ON cell_comments(column_id);
CREATE INDEX IF NOT EXISTS idx_cell_comments_created_by ON cell_comments(created_by);
CREATE INDEX IF NOT EXISTS idx_cell_comments_created_at ON cell_comments(created_at);
CREATE INDEX IF NOT EXISTS idx_cell_comments_is_resolved ON cell_comments(is_resolved);

