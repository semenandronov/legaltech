-- Session context: thread state + per-message semantic index (in-dialog memory).
CREATE TABLE IF NOT EXISTS chat_session_context (
    scope VARCHAR(16) NOT NULL,
    session_key VARCHAR(512) NOT NULL,
    thread_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    conversation_summary TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scope, session_key)
);

CREATE INDEX IF NOT EXISTS idx_chat_session_context_updated
    ON chat_session_context (updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_session_message_index (
    message_id VARCHAR(64) PRIMARY KEY,
    scope VARCHAR(16) NOT NULL,
    session_key VARCHAR(512) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    search_text TEXT NOT NULL DEFAULT '',
    fts_vector tsvector,
    embedding vector(256),
    created_at TIMESTAMPTZ,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_session_msg_session
    ON chat_session_message_index (scope, session_key);

CREATE INDEX IF NOT EXISTS idx_chat_session_msg_fts
    ON chat_session_message_index USING gin (fts_vector);
