-- Migration: Add Harvey-like features tables
-- Created: 2024-12-26

-- =====================================
-- 1. Folders for file organization
-- =====================================
CREATE TABLE IF NOT EXISTS folders (
    id VARCHAR(255) PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    parent_id VARCHAR(255) REFERENCES folders(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    color VARCHAR(50),
    icon VARCHAR(50),
    order_index INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_folders_case_id ON folders(case_id);
CREATE INDEX IF NOT EXISTS ix_folders_parent_id ON folders(parent_id);

-- Add folder_id to files table
ALTER TABLE files ADD COLUMN IF NOT EXISTS folder_id VARCHAR(255) REFERENCES folders(id) ON DELETE SET NULL;
ALTER TABLE files ADD COLUMN IF NOT EXISTS order_index INTEGER DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS starred BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_files_folder_id ON files(folder_id);

-- =====================================
-- 2. File tags
-- =====================================
CREATE TABLE IF NOT EXISTS file_tags (
    id VARCHAR(255) PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    color VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_file_tags_case_id ON file_tags(case_id);

CREATE TABLE IF NOT EXISTS file_tag_associations (
    id VARCHAR(255) PRIMARY KEY,
    file_id VARCHAR(255) NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag_id VARCHAR(255) NOT NULL REFERENCES file_tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_file_tag_associations_file_id ON file_tag_associations(file_id);
CREATE INDEX IF NOT EXISTS ix_file_tag_associations_tag_id ON file_tag_associations(tag_id);

-- =====================================
-- 3. Prompt Library
-- =====================================
CREATE TABLE IF NOT EXISTS prompt_categories (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    icon VARCHAR(50),
    order_index INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prompt_templates (
    id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255) REFERENCES users(id) ON DELETE CASCADE,
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    prompt_text TEXT NOT NULL,
    variables JSONB DEFAULT '[]'::jsonb,
    tags JSONB DEFAULT '[]'::jsonb,
    is_public BOOLEAN DEFAULT FALSE,
    is_system BOOLEAN DEFAULT FALSE,
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_prompt_templates_user_id ON prompt_templates(user_id);
CREATE INDEX IF NOT EXISTS ix_prompt_templates_category ON prompt_templates(category);
CREATE INDEX IF NOT EXISTS ix_prompt_templates_is_system ON prompt_templates(is_system);

-- =====================================
-- 4. Workflow Templates
-- =====================================
CREATE TABLE IF NOT EXISTS workflow_templates (
    id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255) REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) NOT NULL,
    steps JSONB DEFAULT '[]'::jsonb,
    prompts JSONB DEFAULT '{}'::jsonb,
    tabular_template_id VARCHAR(255) REFERENCES tabular_column_templates(id) ON DELETE SET NULL,
    review_columns JSONB DEFAULT '[]'::jsonb,
    is_system BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT FALSE,
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_workflow_templates_user_id ON workflow_templates(user_id);
CREATE INDEX IF NOT EXISTS ix_workflow_templates_category ON workflow_templates(category);
CREATE INDEX IF NOT EXISTS ix_workflow_templates_is_system ON workflow_templates(is_system);

-- =====================================
-- 5. Agent Interactions (Human-in-the-loop)
-- =====================================
CREATE TABLE IF NOT EXISTS agent_interactions (
    id VARCHAR(255) PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_name VARCHAR(100) NOT NULL,
    step_id VARCHAR(255),
    question_type VARCHAR(50) NOT NULL,
    question_text TEXT NOT NULL,
    context TEXT,
    options JSONB,
    user_response TEXT,
    selected_option_id VARCHAR(50),
    status VARCHAR(50) DEFAULT 'pending',
    is_blocking BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    answered_at TIMESTAMP,
    timeout_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_agent_interactions_case_id ON agent_interactions(case_id);
CREATE INDEX IF NOT EXISTS ix_agent_interactions_user_id ON agent_interactions(user_id);
CREATE INDEX IF NOT EXISTS ix_agent_interactions_status ON agent_interactions(status);

-- =====================================
-- 6. Agent Execution Logs
-- =====================================
CREATE TABLE IF NOT EXISTS agent_execution_logs (
    id VARCHAR(255) PRIMARY KEY,
    case_id VARCHAR(255) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    execution_id VARCHAR(255) NOT NULL,
    agent_name VARCHAR(100) NOT NULL,
    step_id VARCHAR(255),
    log_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    details JSONB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_ms VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS ix_agent_execution_logs_case_id ON agent_execution_logs(case_id);
CREATE INDEX IF NOT EXISTS ix_agent_execution_logs_execution_id ON agent_execution_logs(execution_id);

-- =====================================
-- Insert default prompt categories
-- =====================================
INSERT INTO prompt_categories (id, name, display_name, description, icon, order_index) VALUES
    (gen_random_uuid()::text, 'contract', 'Договоры', 'Анализ договоров и контрактов', 'file-text', 1),
    (gen_random_uuid()::text, 'litigation', 'Судебные дела', 'Анализ судебных материалов', 'gavel', 2),
    (gen_random_uuid()::text, 'due_diligence', 'Due Diligence', 'Проверка документов для сделок', 'search', 3),
    (gen_random_uuid()::text, 'research', 'Исследование', 'Юридическое исследование', 'book-open', 4),
    (gen_random_uuid()::text, 'compliance', 'Compliance', 'Проверка соответствия требованиям', 'shield-check', 5),
    (gen_random_uuid()::text, 'custom', 'Прочее', 'Другие запросы', 'folder', 99)
ON CONFLICT (name) DO NOTHING;

