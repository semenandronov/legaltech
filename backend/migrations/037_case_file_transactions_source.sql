-- Row-level PDF source fields for operations registry (CITATION_CONTRACT_V1).
-- Revert: ALTER TABLE case_file_transactions DROP COLUMN IF EXISTS verbatim_row_text, DROP COLUMN IF EXISTS source_references, DROP COLUMN IF EXISTS flow_direction;

ALTER TABLE case_file_transactions
    ADD COLUMN IF NOT EXISTS verbatim_row_text TEXT,
    ADD COLUMN IF NOT EXISTS source_references JSONB,
    ADD COLUMN IF NOT EXISTS flow_direction VARCHAR(16);

CREATE INDEX IF NOT EXISTS idx_cft_file_flow ON case_file_transactions(file_id, flow_direction);
