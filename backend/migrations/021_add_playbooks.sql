-- Migration: Add Playbooks tables
-- Description: Creates tables for Playbook system (contract compliance checking)

-- Playbooks table (набор правил для проверки контрактов)
CREATE TABLE IF NOT EXISTS playbooks (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    contract_type VARCHAR(100) NOT NULL,
    jurisdiction VARCHAR(100),
    is_system BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT FALSE,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for playbooks
CREATE INDEX IF NOT EXISTS idx_playbooks_user_id ON playbooks(user_id);
CREATE INDEX IF NOT EXISTS idx_playbooks_contract_type ON playbooks(contract_type);
CREATE INDEX IF NOT EXISTS idx_playbooks_is_system ON playbooks(is_system);
CREATE INDEX IF NOT EXISTS idx_playbooks_is_public ON playbooks(is_public);

-- Playbook rules table (правила в playbook)
CREATE TABLE IF NOT EXISTS playbook_rules (
    id VARCHAR(36) PRIMARY KEY,
    playbook_id VARCHAR(36) NOT NULL REFERENCES playbooks(id) ON DELETE CASCADE,
    rule_type VARCHAR(50) NOT NULL,
    clause_category VARCHAR(100) NOT NULL,
    rule_name VARCHAR(255) NOT NULL,
    description TEXT,
    condition_type VARCHAR(50) NOT NULL,
    condition_config JSONB NOT NULL DEFAULT '{}',
    extraction_prompt TEXT,
    validation_prompt TEXT,
    suggested_clause_template TEXT,
    fallback_options JSONB,
    priority INTEGER DEFAULT 0,
    severity VARCHAR(20) DEFAULT 'medium',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for playbook_rules
CREATE INDEX IF NOT EXISTS idx_playbook_rules_playbook_id ON playbook_rules(playbook_id);
CREATE INDEX IF NOT EXISTS idx_playbook_rules_rule_type ON playbook_rules(rule_type);
CREATE INDEX IF NOT EXISTS idx_playbook_rules_clause_category ON playbook_rules(clause_category);
CREATE INDEX IF NOT EXISTS idx_playbook_rules_is_active ON playbook_rules(is_active);

-- Playbook checks table (результаты проверки)
CREATE TABLE IF NOT EXISTS playbook_checks (
    id VARCHAR(36) PRIMARY KEY,
    playbook_id VARCHAR(36) REFERENCES playbooks(id) ON DELETE SET NULL,
    document_id VARCHAR(36) NOT NULL,
    case_id VARCHAR(36) REFERENCES cases(id) ON DELETE CASCADE,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    document_name VARCHAR(500),
    document_hash VARCHAR(64),
    overall_status VARCHAR(50) NOT NULL DEFAULT 'in_progress',
    compliance_score DECIMAL(5,2),
    red_line_violations INTEGER DEFAULT 0,
    fallback_issues INTEGER DEFAULT 0,
    no_go_violations INTEGER DEFAULT 0,
    passed_rules INTEGER DEFAULT 0,
    results JSONB NOT NULL DEFAULT '[]',
    redlines JSONB,
    extracted_clauses JSONB,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    processing_time_seconds INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for playbook_checks
CREATE INDEX IF NOT EXISTS idx_playbook_checks_playbook_id ON playbook_checks(playbook_id);
CREATE INDEX IF NOT EXISTS idx_playbook_checks_document_id ON playbook_checks(document_id);
CREATE INDEX IF NOT EXISTS idx_playbook_checks_case_id ON playbook_checks(case_id);
CREATE INDEX IF NOT EXISTS idx_playbook_checks_user_id ON playbook_checks(user_id);
CREATE INDEX IF NOT EXISTS idx_playbook_checks_overall_status ON playbook_checks(overall_status);
CREATE INDEX IF NOT EXISTS idx_playbook_checks_created_at ON playbook_checks(created_at);

-- Add comments
COMMENT ON TABLE playbooks IS 'Playbooks - наборы правил для проверки контрактов';
COMMENT ON TABLE playbook_rules IS 'Правила Playbook - отдельные правила проверки';
COMMENT ON TABLE playbook_checks IS 'Результаты проверки документов против Playbooks';

COMMENT ON COLUMN playbook_rules.rule_type IS 'Тип правила: red_line, fallback, no_go';
COMMENT ON COLUMN playbook_rules.condition_type IS 'Тип условия: must_exist, must_not_exist, value_check, duration_check, text_match, text_not_match';
COMMENT ON COLUMN playbook_checks.overall_status IS 'Статус проверки: compliant, non_compliant, needs_review, in_progress, failed';

