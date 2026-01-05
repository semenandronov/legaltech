-- Migration: Add cell locking fields
-- Created: 2025-01-XX
-- Description: Adds fields for cell locking mechanism

-- Add locking fields to tabular_cells table
ALTER TABLE tabular_cells 
ADD COLUMN IF NOT EXISTS locked_by VARCHAR(255) REFERENCES users(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS lock_expires_at TIMESTAMP WITH TIME ZONE;

-- Index for faster lookup of locked cells
CREATE INDEX IF NOT EXISTS idx_tabular_cells_locked_by ON tabular_cells(locked_by);
CREATE INDEX IF NOT EXISTS idx_tabular_cells_lock_expires ON tabular_cells(lock_expires_at) WHERE locked_by IS NOT NULL;

