-- Migration: Add document_templates table for caching Garant document templates
-- Created: 2024

CREATE TABLE IF NOT EXISTS document_templates (
    id VARCHAR(255) PRIMARY KEY,
    source VARCHAR(50) NOT NULL DEFAULT 'garant',
    source_doc_id VARCHAR(255),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    content TEXT NOT NULL,
    keywords JSONB DEFAULT '[]'::jsonb,
    category VARCHAR(100),
    tags JSONB DEFAULT '[]'::jsonb,
    garant_metadata JSONB,
    user_id VARCHAR(255) REFERENCES users(id) ON DELETE CASCADE,
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    is_public BOOLEAN DEFAULT FALSE,
    is_system BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS ix_document_templates_user_id ON document_templates(user_id);
CREATE INDEX IF NOT EXISTS ix_document_templates_category ON document_templates(category);
CREATE INDEX IF NOT EXISTS ix_document_templates_title ON document_templates(title);
CREATE INDEX IF NOT EXISTS ix_document_templates_keywords ON document_templates USING GIN(keywords);
CREATE INDEX IF NOT EXISTS ix_document_templates_tags ON document_templates USING GIN(tags);
CREATE INDEX IF NOT EXISTS ix_document_templates_source_doc_id ON document_templates(source_doc_id);

-- Комментарии к таблице и полям
COMMENT ON TABLE document_templates IS 'Кэш шаблонов документов из Гаранта для быстрого доступа';
COMMENT ON COLUMN document_templates.source IS 'Источник шаблона: garant, custom';
COMMENT ON COLUMN document_templates.keywords IS 'Ключевые слова для поиска (JSON массив)';
COMMENT ON COLUMN document_templates.tags IS 'Теги для категоризации (JSON массив)';
COMMENT ON COLUMN document_templates.garant_metadata IS 'Метаданные из Гаранта (JSON объект)';

