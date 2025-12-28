-- Migration: Add category, tags, is_system, is_featured, usage_count to tabular_column_templates
-- Date: 2025-01-XX

-- Add new columns to tabular_column_templates table
ALTER TABLE tabular_column_templates
ADD COLUMN IF NOT EXISTS category VARCHAR(100),
ADD COLUMN IF NOT EXISTS tags JSON,
ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS usage_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Create index on category for faster filtering
CREATE INDEX IF NOT EXISTS idx_tabular_column_templates_category ON tabular_column_templates(category);

-- Create index on is_featured for featured templates query
CREATE INDEX IF NOT EXISTS idx_tabular_column_templates_featured ON tabular_column_templates(is_featured);

-- Create index on is_system for system templates query
CREATE INDEX IF NOT EXISTS idx_tabular_column_templates_system ON tabular_column_templates(is_system);

-- Update existing templates to have default values
UPDATE tabular_column_templates
SET category = 'custom',
    tags = '[]'::json,
    is_system = FALSE,
    is_featured = FALSE,
    usage_count = 0,
    updated_at = CURRENT_TIMESTAMP
WHERE category IS NULL;

