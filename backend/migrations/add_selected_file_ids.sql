-- Migration: Add selected_file_ids column to tabular_reviews table
-- Date: 2025-12-25
-- Description: Adds JSON column to store selected file IDs for tabular reviews

-- Add column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'tabular_reviews' 
        AND column_name = 'selected_file_ids'
    ) THEN
        ALTER TABLE tabular_reviews 
        ADD COLUMN selected_file_ids JSON;
        
        COMMENT ON COLUMN tabular_reviews.selected_file_ids IS 'Список выбранных file_id для этой таблицы';
    END IF;
END $$;

