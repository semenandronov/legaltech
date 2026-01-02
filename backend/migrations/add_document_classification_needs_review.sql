-- Migration: Add needs_human_review column to document_classifications table
-- Created: 2025-01-XX

-- Add needs_human_review column
ALTER TABLE document_classifications 
ADD COLUMN IF NOT EXISTS needs_human_review VARCHAR(10) DEFAULT 'false';

-- Update existing records: set needs_human_review=true if confidence < 0.75
UPDATE document_classifications 
SET needs_human_review = 'true' 
WHERE CAST(confidence AS FLOAT) < 0.75 
  AND (needs_human_review IS NULL OR needs_human_review = 'false');

-- Set default for NULL values
UPDATE document_classifications 
SET needs_human_review = 'false' 
WHERE needs_human_review IS NULL;

-- Create index for faster filtering
CREATE INDEX IF NOT EXISTS ix_document_classifications_needs_review 
ON document_classifications(needs_human_review) 
WHERE needs_human_review = 'true';

