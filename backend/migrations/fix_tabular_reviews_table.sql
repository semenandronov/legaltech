-- Fix tabular_reviews table structure
-- This migration fixes the table if it was created incorrectly

-- First, drop the table if it exists with wrong schema
DROP TABLE IF EXISTS tabular_cells CASCADE;
DROP TABLE IF EXISTS tabular_columns CASCADE;
DROP TABLE IF EXISTS tabular_document_statuses CASCADE;
DROP TABLE IF EXISTS tabular_column_templates CASCADE;
DROP TABLE IF EXISTS tabular_reviews CASCADE;

-- Now create tables with correct schema
CREATE TABLE IF NOT EXISTS tabular_reviews (
    id VARCHAR(255) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    case_id VARCHAR(255) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'draft',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tabular_reviews_case_id ON tabular_reviews(case_id);
CREATE INDEX IF NOT EXISTS idx_tabular_reviews_user_id ON tabular_reviews(user_id);

CREATE TABLE IF NOT EXISTS tabular_columns (
    id VARCHAR(255) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    review_id VARCHAR(255) NOT NULL REFERENCES tabular_reviews(id) ON DELETE CASCADE,
    column_label VARCHAR(255) NOT NULL,
    column_type VARCHAR(50) NOT NULL,
    prompt TEXT NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tabular_columns_review_id ON tabular_columns(review_id);

CREATE TABLE IF NOT EXISTS tabular_cells (
    id VARCHAR(255) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    review_id VARCHAR(255) NOT NULL REFERENCES tabular_reviews(id) ON DELETE CASCADE,
    column_id VARCHAR(255) NOT NULL REFERENCES tabular_columns(id) ON DELETE CASCADE,
    file_id VARCHAR(255) NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    cell_value TEXT,
    verbatim_extract TEXT,
    reasoning TEXT,
    confidence_score DECIMAL(5, 2),
    source_page INTEGER,
    source_section VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(review_id, column_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_tabular_cells_review_id ON tabular_cells(review_id);
CREATE INDEX IF NOT EXISTS idx_tabular_cells_column_id ON tabular_cells(column_id);
CREATE INDEX IF NOT EXISTS idx_tabular_cells_file_id ON tabular_cells(file_id);

CREATE TABLE IF NOT EXISTS tabular_column_templates (
    id VARCHAR(255) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id VARCHAR(255) REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    columns JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tabular_column_templates_user_id ON tabular_column_templates(user_id);

CREATE TABLE IF NOT EXISTS tabular_document_statuses (
    id VARCHAR(255) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    review_id VARCHAR(255) NOT NULL REFERENCES tabular_reviews(id) ON DELETE CASCADE,
    file_id VARCHAR(255) NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    reviewed_by VARCHAR(255) REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(review_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_tabular_document_statuses_review_id ON tabular_document_statuses(review_id);
CREATE INDEX IF NOT EXISTS idx_tabular_document_statuses_file_id ON tabular_document_statuses(file_id);

