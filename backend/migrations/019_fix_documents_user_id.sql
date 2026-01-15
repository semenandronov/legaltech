-- Migration: Fix documents table user_id column name
-- If column is named "user_id" but should be "userId", rename it
-- If column doesn't exist, create it

-- Check if column exists with wrong name and rename
DO $$
BEGIN
    -- Check if user_id exists (snake_case)
    IF EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'documents' 
        AND column_name = 'user_id'
    ) THEN
        -- Rename to userId (camelCase)
        ALTER TABLE documents RENAME COLUMN user_id TO "userId";
        RAISE NOTICE 'Renamed user_id to userId';
    END IF;
    
    -- If neither exists, create userId column
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'documents' 
        AND column_name IN ('user_id', 'userId')
    ) THEN
        ALTER TABLE documents ADD COLUMN "userId" VARCHAR;
        ALTER TABLE documents ADD CONSTRAINT fk_documents_user FOREIGN KEY ("userId") REFERENCES users(id) ON DELETE CASCADE;
        CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents("userId");
        RAISE NOTICE 'Created userId column';
    END IF;
END $$;

