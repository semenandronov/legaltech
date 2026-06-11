-- Migration: Agent runs (Legora-style deep agent execution ledger)
-- Replaces dropped workflow_* tables with a focused run model.

CREATE TABLE IF NOT EXISTS agent_runs (
    id VARCHAR(36) PRIMARY KEY,
    case_id VARCHAR(36) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id VARCHAR(36) NOT NULL UNIQUE,
    user_task TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    input_config JSONB,
    selected_file_ids JSONB,
    artifacts JSONB,
    todos JSONB,
    result_summary TEXT,
    error_message TEXT,
    langfuse_trace_id VARCHAR(64),
    total_tool_calls INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_case_id ON agent_runs(case_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_user_id ON agent_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at ON agent_runs(created_at DESC);

COMMENT ON TABLE agent_runs IS 'Запуски deep-агента (Legora-style): задача, статус, артефакты, thread_id для LangGraph';
COMMENT ON COLUMN agent_runs.thread_id IS 'LangGraph configurable.thread_id (обычно = id запуска)';
COMMENT ON COLUMN agent_runs.status IS 'pending | running | waiting_for_user | completed | failed | cancelled';
