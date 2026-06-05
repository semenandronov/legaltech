-- Migration: draft_template_field_catalog — прединдексированные поля шаблонов Draft

CREATE TABLE IF NOT EXISTS draft_template_field_catalog (
    id VARCHAR(255) PRIMARY KEY,
    template_key VARCHAR(255) NOT NULL UNIQUE,
    content_sha256 VARCHAR(64) NOT NULL DEFAULT '',
    field_specs JSONB NOT NULL DEFAULT '[]'::jsonb,
    indexed_html TEXT NOT NULL DEFAULT '',
    indexer_version VARCHAR(32) NOT NULL DEFAULT '1',
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_draft_template_field_catalog_template_key
    ON draft_template_field_catalog(template_key);

COMMENT ON TABLE draft_template_field_catalog IS 'Каталог плейсхолдеров шаблона Draft с retrieval_query и indexed_html';
