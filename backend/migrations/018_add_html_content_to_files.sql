-- Migration: Add html_content column to files table for caching HTML representation
-- Created: 2025-01-XX
-- Purpose: Cache HTML conversion results for faster document viewing

-- Add html_content column to files table
ALTER TABLE files ADD COLUMN IF NOT EXISTS html_content TEXT;

-- Add comment for documentation
COMMENT ON COLUMN files.html_content IS 'Cached HTML representation of the file for faster viewing and editing';

-- Create index for faster lookups (partial index for files with cached HTML)
CREATE INDEX IF NOT EXISTS ix_files_html_content ON files(id) WHERE html_content IS NOT NULL;

