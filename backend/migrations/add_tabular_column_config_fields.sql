-- Migration: Add column_config, is_pinned to tabular_columns and source_references to tabular_cells
-- Created: 2025-01-XX
-- Description: Adds support for tag options configuration, pinned columns, and source references for reasoning

-- Add column_config to tabular_columns (for tag/multiple_tags options)
ALTER TABLE tabular_columns 
ADD COLUMN IF NOT EXISTS column_config JSONB;

-- Add is_pinned to tabular_columns (for pinning columns)
ALTER TABLE tabular_columns 
ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN DEFAULT FALSE;

-- Add source_references to tabular_cells (for storing source citations)
ALTER TABLE tabular_cells 
ADD COLUMN IF NOT EXISTS source_references JSONB;

-- Create index on is_pinned for faster queries
CREATE INDEX IF NOT EXISTS idx_tabular_columns_is_pinned ON tabular_columns(is_pinned) WHERE is_pinned = TRUE;

-- Add comment for documentation
COMMENT ON COLUMN tabular_columns.column_config IS 'Configuration for tag/multiple_tags columns: {options: [{label, color}], allow_custom: bool}';
COMMENT ON COLUMN tabular_columns.is_pinned IS 'Whether the column is pinned (always visible on left side)';
COMMENT ON COLUMN tabular_cells.source_references IS 'Source references for reasoning: [{page: int, section: str, text: str}]';


