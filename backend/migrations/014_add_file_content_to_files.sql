-- Migration: Add file_content column to files table for storing binary file content in PostgreSQL
-- This allows files to persist across deployments on ephemeral filesystems (e.g., Render)

ALTER TABLE files ADD COLUMN IF NOT EXISTS file_content BYTEA;

-- Add comment for documentation
COMMENT ON COLUMN files.file_content IS 'Binary content of the original file (PDF, DOCX, XLSX, etc.) stored in database for persistence';

