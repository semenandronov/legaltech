-- Migration: Add review queue support
-- Created: 2025-01-XX
-- Description: Adds review_rules to TabularReview and creates review_queue_items table

-- Add review_rules column to tabular_reviews
ALTER TABLE tabular_reviews 
  ADD COLUMN IF NOT EXISTS review_rules JSONB;

-- Create GIN index for review_rules JSONB queries
CREATE INDEX IF NOT EXISTS idx_tabular_reviews_review_rules_gin ON tabular_reviews USING GIN(review_rules);

-- Create review_queue_items table
CREATE TABLE IF NOT EXISTS review_queue_items (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tabular_review_id VARCHAR NOT NULL,
    file_id VARCHAR NOT NULL,
    column_id VARCHAR NOT NULL,
    cell_id VARCHAR NOT NULL,
    priority INTEGER NOT NULL DEFAULT 5,
    reason VARCHAR(255) NOT NULL,
    is_reviewed BOOLEAN DEFAULT false,
    reviewed_by VARCHAR,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_review_queue_items_review FOREIGN KEY (tabular_review_id) REFERENCES tabular_reviews(id) ON DELETE CASCADE,
    CONSTRAINT fk_review_queue_items_file FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    CONSTRAINT fk_review_queue_items_column FOREIGN KEY (column_id) REFERENCES tabular_columns(id) ON DELETE CASCADE,
    CONSTRAINT fk_review_queue_items_cell FOREIGN KEY (cell_id) REFERENCES tabular_cells(id) ON DELETE CASCADE,
    CONSTRAINT fk_review_queue_items_reviewer FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT check_review_queue_priority CHECK (priority >= 1 AND priority <= 5)
);

-- Indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_review_queue_items_review_id ON review_queue_items(tabular_review_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_items_file_id ON review_queue_items(file_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_items_column_id ON review_queue_items(column_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_items_cell_id ON review_queue_items(cell_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_items_priority ON review_queue_items(priority);
CREATE INDEX IF NOT EXISTS idx_review_queue_items_is_reviewed ON review_queue_items(is_reviewed);
CREATE INDEX IF NOT EXISTS idx_review_queue_items_created_at ON review_queue_items(created_at);

-- Composite index for common queries
CREATE INDEX IF NOT EXISTS idx_review_queue_items_review_reviewed ON review_queue_items(tabular_review_id, is_reviewed, priority);

-- Add comment
COMMENT ON COLUMN tabular_reviews.review_rules IS 'Review queue rules: {low_confidence_threshold, critical_columns, always_review_types, conflict_priority, ocr_quality_threshold}';
COMMENT ON TABLE review_queue_items IS 'Items in review queue for quality control';

