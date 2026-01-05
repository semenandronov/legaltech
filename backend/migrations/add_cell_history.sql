-- Migration: Add cell_history table for version history
-- Created: 2025-01-XX
-- Description: Creates table for tracking cell value changes over time

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table for cell history (version tracking)
CREATE TABLE IF NOT EXISTS cell_history (
    id VARCHAR(255) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tabular_review_id VARCHAR(255) NOT NULL REFERENCES tabular_reviews(id) ON DELETE CASCADE,
    file_id VARCHAR(255) NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    column_id VARCHAR(255) NOT NULL REFERENCES tabular_columns(id) ON DELETE CASCADE,
    cell_value TEXT,
    verbatim_extract TEXT,
    reasoning TEXT,
    source_references JSONB,
    confidence_score DECIMAL(3, 2),
    source_page INTEGER,
    source_section VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',
    changed_by VARCHAR(255) REFERENCES users(id) ON DELETE SET NULL,
    change_type VARCHAR(50) NOT NULL, -- 'created', 'updated', 'deleted', 'reverted'
    previous_cell_value TEXT,
    change_reason TEXT, -- Optional reason for the change
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_cell_history_review FOREIGN KEY (tabular_review_id) REFERENCES tabular_reviews(id) ON DELETE CASCADE,
    CONSTRAINT fk_cell_history_file FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    CONSTRAINT fk_cell_history_column FOREIGN KEY (column_id) REFERENCES tabular_columns(id) ON DELETE CASCADE
);

-- Indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_cell_history_review_id ON cell_history(tabular_review_id);
CREATE INDEX IF NOT EXISTS idx_cell_history_file_id ON cell_history(file_id);
CREATE INDEX IF NOT EXISTS idx_cell_history_column_id ON cell_history(column_id);
CREATE INDEX IF NOT EXISTS idx_cell_history_file_column ON cell_history(file_id, column_id);
CREATE INDEX IF NOT EXISTS idx_cell_history_created_at ON cell_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cell_history_changed_by ON cell_history(changed_by);

-- Composite index for common queries (get history for a specific cell)
CREATE INDEX IF NOT EXISTS idx_cell_history_cell_lookup ON cell_history(file_id, column_id, tabular_review_id, created_at DESC);

