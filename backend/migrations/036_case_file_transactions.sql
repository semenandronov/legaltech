-- Structured table rows (bank statements, payment registers) for deterministic chat queries.
-- Revert: DROP TABLE IF EXISTS case_file_transactions;
-- Disable feature: CASE_FILE_TRANSACTIONS_ENABLED=false

CREATE TABLE IF NOT EXISTS case_file_transactions (
    id VARCHAR(36) PRIMARY KEY,
    case_id VARCHAR(36) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    file_id VARCHAR(36) NOT NULL,
    global_row_index INTEGER NOT NULL,
    table_index INTEGER NOT NULL DEFAULT 0,
    row_index INTEGER NOT NULL DEFAULT 0,
    operation_date DATE,
    operation_datetime_text TEXT,
    amount_rub NUMERIC(18, 2),
    amount_raw TEXT,
    description TEXT,
    row_columns JSONB NOT NULL DEFAULT '{}'::jsonb,
    page_start INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    source_filename VARCHAR(512),
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    CONSTRAINT uq_case_file_transactions_file_row UNIQUE (file_id, global_row_index)
);

CREATE INDEX IF NOT EXISTS idx_cft_case_id ON case_file_transactions(case_id);
CREATE INDEX IF NOT EXISTS idx_cft_file_id ON case_file_transactions(file_id);
CREATE INDEX IF NOT EXISTS idx_cft_case_op_date ON case_file_transactions(case_id, operation_date);
