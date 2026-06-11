-- Migration: Distributed event bus for agent runs (replay + LISTEN/NOTIFY hints)

ALTER TABLE agent_runs
    ADD COLUMN IF NOT EXISTS worker_instance_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_agent_runs_worker_instance
    ON agent_runs(worker_instance_id)
    WHERE worker_instance_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_runs_pending_worker
    ON agent_runs(status, created_at)
    WHERE status IN ('pending', 'running', 'waiting_for_user');

CREATE TABLE IF NOT EXISTS agent_run_events (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_run_events_run_seq UNIQUE (run_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_seq
    ON agent_run_events(run_id, seq);

COMMENT ON TABLE agent_run_events IS 'Append-only SSE event log for agent runs; NOTIFY carries seq hint only';
COMMENT ON COLUMN agent_runs.worker_instance_id IS 'Pod/process that claimed execution';
COMMENT ON COLUMN agent_runs.cancel_requested_at IS 'Distributed cancel signal timestamp';
