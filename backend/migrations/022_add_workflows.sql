-- Migration: Add Workflow tables
-- Description: Creates tables for Agentic Workflow system

-- Workflow Definitions table (шаблоны workflow)
CREATE TABLE IF NOT EXISTS workflow_definitions (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) NOT NULL,
    default_plan JSONB,
    available_tools JSONB NOT NULL DEFAULT '[]',
    output_schema JSONB,
    planning_prompt TEXT,
    summary_prompt TEXT,
    max_steps INTEGER DEFAULT 50,
    timeout_minutes INTEGER DEFAULT 60,
    requires_approval BOOLEAN DEFAULT FALSE,
    is_system BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT FALSE,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
    usage_count INTEGER DEFAULT 0,
    avg_execution_time INTEGER,
    success_rate DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for workflow_definitions
CREATE INDEX IF NOT EXISTS idx_workflow_definitions_user_id ON workflow_definitions(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_definitions_category ON workflow_definitions(category);
CREATE INDEX IF NOT EXISTS idx_workflow_definitions_is_system ON workflow_definitions(is_system);
CREATE INDEX IF NOT EXISTS idx_workflow_definitions_is_public ON workflow_definitions(is_public);

-- Workflow Executions table (запуски workflow)
CREATE TABLE IF NOT EXISTS workflow_executions (
    id VARCHAR(36) PRIMARY KEY,
    definition_id VARCHAR(36) REFERENCES workflow_definitions(id) ON DELETE SET NULL,
    case_id VARCHAR(36) REFERENCES cases(id) ON DELETE CASCADE,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    user_task TEXT NOT NULL,
    input_config JSONB,
    selected_file_ids JSONB,
    execution_plan JSONB,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    current_step_id VARCHAR(100),
    progress_percent INTEGER DEFAULT 0,
    status_message TEXT,
    results JSONB,
    artifacts JSONB,
    summary TEXT,
    error_message TEXT,
    error_step_id VARCHAR(100),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    total_llm_calls INTEGER DEFAULT 0,
    total_tokens_used INTEGER DEFAULT 0,
    total_steps_completed INTEGER DEFAULT 0,
    total_steps_failed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for workflow_executions
CREATE INDEX IF NOT EXISTS idx_workflow_executions_definition_id ON workflow_executions(definition_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_case_id ON workflow_executions(case_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_user_id ON workflow_executions(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_status ON workflow_executions(status);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_created_at ON workflow_executions(created_at);

-- Workflow Steps table (шаги выполнения)
CREATE TABLE IF NOT EXISTS workflow_steps (
    id VARCHAR(36) PRIMARY KEY,
    execution_id VARCHAR(36) NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
    step_id VARCHAR(100) NOT NULL,
    sequence_number INTEGER NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    step_type VARCHAR(100) NOT NULL,
    description TEXT,
    tool_name VARCHAR(100),
    tool_params JSONB,
    depends_on JSONB,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    result JSONB,
    output_summary TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds INTEGER,
    llm_calls INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for workflow_steps
CREATE INDEX IF NOT EXISTS idx_workflow_steps_execution_id ON workflow_steps(execution_id);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_status ON workflow_steps(status);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_step_id ON workflow_steps(step_id);

-- Add comments
COMMENT ON TABLE workflow_definitions IS 'Шаблоны Workflow для автономного выполнения задач';
COMMENT ON TABLE workflow_executions IS 'Запуски Workflow с планом и результатами';
COMMENT ON TABLE workflow_steps IS 'Отдельные шаги выполнения Workflow';

COMMENT ON COLUMN workflow_definitions.category IS 'Категория: due_diligence, litigation, compliance, research, contract_analysis, custom';
COMMENT ON COLUMN workflow_executions.status IS 'Статус: pending, planning, awaiting_approval, executing, validating, generating_report, completed, failed, cancelled';
COMMENT ON COLUMN workflow_steps.step_type IS 'Тип шага: tool_call, analysis, validation, aggregation, human_review';

