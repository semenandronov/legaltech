-- Migration: Add file_path column to files table for storing original file paths
-- Created: 2025-12-29

-- Add file_path column to files table
ALTER TABLE files ADD COLUMN IF NOT EXISTS file_path VARCHAR(512);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS ix_files_file_path ON files(file_path) WHERE file_path IS NOT NULL;

