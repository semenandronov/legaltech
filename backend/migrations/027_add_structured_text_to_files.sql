-- Full structured source text for case files (Docling / legal chunker), used by editor paperclip.

ALTER TABLE files ADD COLUMN IF NOT EXISTS structured_text TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS structured_text_format VARCHAR(32);

COMMENT ON COLUMN files.structured_text IS 'Full document text with structure (markdown-oriented) for editor attach full-context';
COMMENT ON COLUMN files.structured_text_format IS 'plain | markdown | macro_join';
