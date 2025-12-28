-- Migration: Add LangGraph checkpoint tables for state persistence
-- These tables are used by langgraph.checkpoint.postgres.PostgresSaver
-- Note: PostgresSaver.setup() can create these tables automatically, but this migration ensures they exist

-- Checkpoints table stores the checkpoint state
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB,
    metadata JSONB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_id ON checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_parent ON checkpoints(parent_checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_type ON checkpoints(type);

-- GIN index for JSONB queries
CREATE INDEX IF NOT EXISTS idx_checkpoints_checkpoint_gin ON checkpoints USING GIN(checkpoint);
CREATE INDEX IF NOT EXISTS idx_checkpoints_metadata_gin ON checkpoints USING GIN(metadata);

-- Checkpoint_blobs table for large binary data (if needed)
CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

-- Indexes for checkpoint_blobs
CREATE INDEX IF NOT EXISTS idx_checkpoint_blobs_thread_id ON checkpoint_blobs(thread_id);

-- Writes table for tracking writes (for optimistic locking)
CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT,
    type TEXT,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, task_id, idx)
);

-- Indexes for checkpoint_writes
CREATE INDEX IF NOT EXISTS idx_checkpoint_writes_thread_id ON checkpoint_writes(thread_id);
CREATE INDEX IF NOT EXISTS idx_checkpoint_writes_checkpoint_id ON checkpoint_writes(checkpoint_id);

COMMENT ON TABLE checkpoints IS 'LangGraph checkpoint storage for state persistence';
COMMENT ON TABLE checkpoint_blobs IS 'LangGraph checkpoint blobs for large binary data';
COMMENT ON TABLE checkpoint_writes IS 'LangGraph checkpoint writes for tracking state updates';

