-- Add evidence bundle to chat messages (server-owned citations + retrieval metadata).
-- Goal: allow safe recap / referential follow-ups without re-running retrieval.

ALTER TABLE chat_messages
ADD COLUMN IF NOT EXISTS evidence JSON;

ALTER TABLE global_assistant_messages
ADD COLUMN IF NOT EXISTS evidence JSON;

COMMENT ON COLUMN chat_messages.evidence IS 'Canonical evidence bundle for assistant answers: citations[], retrieval_metadata, case_numbers, etc.';
COMMENT ON COLUMN global_assistant_messages.evidence IS 'Canonical evidence bundle for assistant answers: citations[], retrieval_metadata, case_numbers, etc.';

