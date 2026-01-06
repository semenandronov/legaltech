-- Migration: Add table modes and entity config to Tabular Review
-- Created: 2025-01-XX
-- Description: Adds table_mode and entity_config fields for Entity Table and Fact Table modes

-- Add new columns to tabular_reviews table
ALTER TABLE tabular_reviews 
  ADD COLUMN IF NOT EXISTS table_mode VARCHAR(50) DEFAULT 'document',
  ADD COLUMN IF NOT EXISTS entity_config JSONB;

-- Update existing rows to have default table_mode
UPDATE tabular_reviews 
SET table_mode = 'document' 
WHERE table_mode IS NULL;

-- Add constraint for table_mode values
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints 
    WHERE constraint_name = 'check_tabular_reviews_table_mode' 
    AND table_name = 'tabular_reviews'
  ) THEN
    ALTER TABLE tabular_reviews 
      ADD CONSTRAINT check_tabular_reviews_table_mode 
      CHECK (table_mode IN ('document', 'entity', 'fact'));
  END IF;
END $$;

-- Create index for table_mode for faster filtering
CREATE INDEX IF NOT EXISTS idx_tabular_reviews_table_mode ON tabular_reviews(table_mode);

-- Create GIN index for entity_config JSONB queries
CREATE INDEX IF NOT EXISTS idx_tabular_reviews_entity_config_gin ON tabular_reviews USING GIN(entity_config);

-- Add comment explaining the new fields
COMMENT ON COLUMN tabular_reviews.table_mode IS 'Table mode: document (1 row = 1 document), entity (1 row = entity inside document), fact (1 row = fact)';
COMMENT ON COLUMN tabular_reviews.entity_config IS 'Configuration for entity mode: {entity_type, extraction_prompt, grouping_key}';

