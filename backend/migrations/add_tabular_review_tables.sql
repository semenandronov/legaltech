-- Migration: Add Tabular Review tables
-- Created: 2025-01-XX
-- Description: Creates tables for Tabular Review functionality

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table for Tabular Review projects
CREATE TABLE IF NOT EXISTS tabular_reviews (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    case_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_tabular_reviews_case FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    CONSTRAINT fk_tabular_reviews_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_tabular_reviews_case_id ON tabular_reviews(case_id);
CREATE INDEX IF NOT EXISTS idx_tabular_reviews_user_id ON tabular_reviews(user_id);
CREATE INDEX IF NOT EXISTS idx_tabular_reviews_status ON tabular_reviews(status);

-- Table for column definitions (questions)
CREATE TABLE IF NOT EXISTS tabular_columns (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tabular_review_id VARCHAR NOT NULL,
    column_label VARCHAR(255) NOT NULL,
    column_type VARCHAR(50) NOT NULL,
    prompt TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_tabular_columns_review FOREIGN KEY (tabular_review_id) REFERENCES tabular_reviews(id) ON DELETE CASCADE
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_tabular_columns_review_id ON tabular_columns(tabular_review_id);
CREATE INDEX IF NOT EXISTS idx_tabular_columns_order ON tabular_columns(tabular_review_id, order_index);

-- Table for cell values (AI responses)
CREATE TABLE IF NOT EXISTS tabular_cells (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tabular_review_id VARCHAR NOT NULL,
    file_id VARCHAR NOT NULL,
    column_id VARCHAR NOT NULL,
    cell_value TEXT,
    verbatim_extract TEXT,
    reasoning TEXT,
    confidence_score DECIMAL(3, 2),
    source_page INTEGER,
    source_section VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_tabular_cells_review FOREIGN KEY (tabular_review_id) REFERENCES tabular_reviews(id) ON DELETE CASCADE,
    CONSTRAINT fk_tabular_cells_file FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    CONSTRAINT fk_tabular_cells_column FOREIGN KEY (column_id) REFERENCES tabular_columns(id) ON DELETE CASCADE,
    CONSTRAINT uq_tabular_cell_file_column UNIQUE (file_id, column_id)
);

-- Indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_tabular_cells_review_id ON tabular_cells(tabular_review_id);
CREATE INDEX IF NOT EXISTS idx_tabular_cells_file_id ON tabular_cells(file_id);
CREATE INDEX IF NOT EXISTS idx_tabular_cells_column_id ON tabular_cells(column_id);
CREATE INDEX IF NOT EXISTS idx_tabular_cells_status ON tabular_cells(status);

-- Table for column templates
CREATE TABLE IF NOT EXISTS tabular_column_templates (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    columns JSONB NOT NULL,
    is_public BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_tabular_templates_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_tabular_templates_user_id ON tabular_column_templates(user_id);
CREATE INDEX IF NOT EXISTS idx_tabular_templates_public ON tabular_column_templates(is_public);

-- Table for document review statuses
CREATE TABLE IF NOT EXISTS tabular_document_status (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tabular_review_id VARCHAR NOT NULL,
    file_id VARCHAR NOT NULL,
    user_id VARCHAR,
    status VARCHAR(50) DEFAULT 'not_reviewed',
    locked BOOLEAN DEFAULT false,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_tabular_doc_status_review FOREIGN KEY (tabular_review_id) REFERENCES tabular_reviews(id) ON DELETE CASCADE,
    CONSTRAINT fk_tabular_doc_status_file FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    CONSTRAINT fk_tabular_doc_status_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT uq_tabular_doc_status UNIQUE (tabular_review_id, file_id, user_id)
);

-- Indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_tabular_doc_status_review_id ON tabular_document_status(tabular_review_id);
CREATE INDEX IF NOT EXISTS idx_tabular_doc_status_file_id ON tabular_document_status(file_id);
CREATE INDEX IF NOT EXISTS idx_tabular_doc_status_user_id ON tabular_document_status(user_id);
CREATE INDEX IF NOT EXISTS idx_tabular_doc_status_status ON tabular_document_status(status);

