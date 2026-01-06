-- Migration: Add conflicts and candidates support to Tabular Review
-- Created: 2025-01-XX
-- Description: Adds normalized_value, candidates, conflict_resolution fields and new status values

-- Add new columns to tabular_cells table
ALTER TABLE tabular_cells 
  ADD COLUMN IF NOT EXISTS normalized_value TEXT,
  ADD COLUMN IF NOT EXISTS candidates JSONB,
  ADD COLUMN IF NOT EXISTS conflict_resolution JSONB;

-- Add source_references if it doesn't exist (might have been added in a different migration)
ALTER TABLE tabular_cells 
  ADD COLUMN IF NOT EXISTS source_references JSONB;

-- Add locking fields if they don't exist
ALTER TABLE tabular_cells 
  ADD COLUMN IF NOT EXISTS locked_by VARCHAR,
  ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP,
  ADD COLUMN IF NOT EXISTS lock_expires_at TIMESTAMP;

-- Add foreign key for locked_by if column was just added
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints 
    WHERE constraint_name = 'fk_tabular_cells_locked_by' 
    AND table_name = 'tabular_cells'
  ) THEN
    ALTER TABLE tabular_cells 
      ADD CONSTRAINT fk_tabular_cells_locked_by 
      FOREIGN KEY (locked_by) REFERENCES users(id) ON DELETE SET NULL;
  END IF;
END $$;

-- Create index for lock_expires_at for efficient cleanup queries
CREATE INDEX IF NOT EXISTS idx_tabular_cells_lock_expires_at ON tabular_cells(lock_expires_at);

-- Create GIN index for candidates JSONB queries
CREATE INDEX IF NOT EXISTS idx_tabular_cells_candidates_gin ON tabular_cells USING GIN(candidates);

-- Create GIN index for conflict_resolution JSONB queries
CREATE INDEX IF NOT EXISTS idx_tabular_cells_conflict_resolution_gin ON tabular_cells USING GIN(conflict_resolution);

-- Update status constraint to include new values
-- First, drop existing constraint if it exists (PostgreSQL doesn't support ALTER CONSTRAINT for CHECK)
DO $$
BEGIN
  -- Drop constraint if it exists
  IF EXISTS (
    SELECT 1 FROM information_schema.table_constraints 
    WHERE constraint_name = 'check_tabular_cells_status' 
    AND table_name = 'tabular_cells'
  ) THEN
    ALTER TABLE tabular_cells DROP CONSTRAINT check_tabular_cells_status;
  END IF;
  
  -- Add new constraint with all status values
  ALTER TABLE tabular_cells 
    ADD CONSTRAINT check_tabular_cells_status 
    CHECK (status IN ('pending', 'processing', 'completed', 'reviewed', 'conflict', 'empty', 'n_a'));
END $$;

-- Add comment explaining the new fields
COMMENT ON COLUMN tabular_cells.normalized_value IS 'Normalized value separate from cell_value (e.g., normalized date, number)';
COMMENT ON COLUMN tabular_cells.candidates IS 'Array of candidate values found during extraction: [{value, confidence, source_page, verbatim, reasoning, normalized_value}]';
COMMENT ON COLUMN tabular_cells.conflict_resolution IS 'Metadata about conflict resolution: {resolved_by, resolution_method, selected_candidate_id, resolved_at}';

