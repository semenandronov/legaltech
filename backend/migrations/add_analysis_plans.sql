-- Migration: Add analysis_plans table for storing analysis plans with user approval
-- Created: 2025-01-XX

CREATE TABLE IF NOT EXISTS analysis_plans (
    id VARCHAR PRIMARY KEY,
    case_id VARCHAR NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_task TEXT NOT NULL,
    plan_data JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending_approval',
    confidence VARCHAR(10),
    validation_result JSONB,
    tables_to_create JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP,
    executed_at TIMESTAMP
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_analysis_plans_case_id ON analysis_plans(case_id);
CREATE INDEX IF NOT EXISTS idx_analysis_plans_user_id ON analysis_plans(user_id);
CREATE INDEX IF NOT EXISTS idx_analysis_plans_status ON analysis_plans(status);
CREATE INDEX IF NOT EXISTS idx_analysis_plans_created_at ON analysis_plans(created_at);

-- Add comment
COMMENT ON TABLE analysis_plans IS 'Stores analysis plans for user approval before execution';

