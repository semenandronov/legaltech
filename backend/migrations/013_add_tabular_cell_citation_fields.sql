-- Migration: Add citation fields to tabular_cells table
-- Phase 4: Deep Links in Tabular Review
-- Adds primary_source_doc_id, primary_source_char_start, primary_source_char_end, verified_flag fields

-- Add primary_source_doc_id column (nullable for backward compatibility, indexed for performance)
ALTER TABLE tabular_cells 
ADD COLUMN IF NOT EXISTS primary_source_doc_id VARCHAR;

CREATE INDEX IF NOT EXISTS idx_tabular_cells_primary_source_doc_id ON tabular_cells(primary_source_doc_id);

-- Add primary_source_char_start column (nullable for backward compatibility)
ALTER TABLE tabular_cells 
ADD COLUMN IF NOT EXISTS primary_source_char_start INTEGER;

-- Add primary_source_char_end column (nullable for backward compatibility)
ALTER TABLE tabular_cells 
ADD COLUMN IF NOT EXISTS primary_source_char_end INTEGER;

-- Add verified_flag column (nullable for backward compatibility)
ALTER TABLE tabular_cells 
ADD COLUMN IF NOT EXISTS verified_flag BOOLEAN;

-- Add comments
COMMENT ON COLUMN tabular_cells.primary_source_doc_id IS 'Document ID основного источника для deep links';
COMMENT ON COLUMN tabular_cells.primary_source_char_start IS 'Начальная позиция символа в исходном документе';
COMMENT ON COLUMN tabular_cells.primary_source_char_end IS 'Конечная позиция символа в исходном документе';
COMMENT ON COLUMN tabular_cells.verified_flag IS 'Флаг верификации цитаты (true = verified, false = unverified, NULL = not checked)';


