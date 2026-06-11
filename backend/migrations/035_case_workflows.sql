-- Saved workflow scenarios per case (Legora-style library, user-authored).

CREATE TABLE IF NOT EXISTS case_workflows (
    id VARCHAR(36) PRIMARY KEY,
    case_id VARCHAR(36) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(256) NOT NULL,
    description TEXT,
    user_task TEXT NOT NULL,
    default_file_ids JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_case_workflows_case_id ON case_workflows(case_id);
CREATE INDEX IF NOT EXISTS idx_case_workflows_user_id ON case_workflows(user_id);
