-- Migration: Add planning_metrics table for tracking planning and execution quality
-- Created: 2025-01-XX

CREATE TABLE IF NOT EXISTS planning_metrics (
    id VARCHAR PRIMARY KEY,
    case_id VARCHAR NOT NULL,
    user_id VARCHAR,
    
    -- Planning metrics
    planning_time_seconds FLOAT,
    plan_confidence FLOAT,
    plan_validation_passed VARCHAR,
    plan_issues_count INTEGER DEFAULT 0,
    
    -- Execution metrics
    execution_time_seconds FLOAT,
    total_steps INTEGER DEFAULT 0,
    completed_steps INTEGER DEFAULT 0,
    failed_steps INTEGER DEFAULT 0,
    adaptations_count INTEGER DEFAULT 0,
    
    -- Quality metrics
    average_confidence FLOAT,
    average_completeness FLOAT,
    average_accuracy FLOAT,
    
    -- Plan details
    plan_goals_count INTEGER DEFAULT 0,
    plan_strategy VARCHAR,
    tools_used JSONB,
    sources_used JSONB,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Additional metadata
    metadata JSONB
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_planning_metrics_case_id ON planning_metrics(case_id);
CREATE INDEX IF NOT EXISTS idx_planning_metrics_user_id ON planning_metrics(user_id);
CREATE INDEX IF NOT EXISTS idx_planning_metrics_created_at ON planning_metrics(created_at);

-- Add foreign key constraints if tables exist
-- Note: These are optional and may fail if tables don't exist
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'cases') THEN
        ALTER TABLE planning_metrics 
        ADD CONSTRAINT fk_planning_metrics_case_id 
        FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE;
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        ALTER TABLE planning_metrics 
        ADD CONSTRAINT fk_planning_metrics_user_id 
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
    END IF;
EXCEPTION
    WHEN others THEN
        -- Ignore constraint errors if tables don't exist
        NULL;
END $$;

