-- Add folder_id column to files table (for folder organization)
ALTER TABLE files ADD COLUMN IF NOT EXISTS folder_id VARCHAR(255) REFERENCES folders(id) ON DELETE SET NULL;

-- Create index for folder_id
CREATE INDEX IF NOT EXISTS ix_files_folder_id ON files(folder_id);

-- Add order_index column for ordering within folders
ALTER TABLE files ADD COLUMN IF NOT EXISTS order_index INTEGER DEFAULT 0;

-- Add starred column for favorites
ALTER TABLE files ADD COLUMN IF NOT EXISTS starred BOOLEAN DEFAULT FALSE;
