-- Case sharing: members + email invites
-- Backfill: every existing case owner becomes case_members.role = owner

CREATE TABLE IF NOT EXISTS case_members (
    id VARCHAR PRIMARY KEY,
    case_id VARCHAR NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'editor',
    added_by VARCHAR REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_case_members_case_user UNIQUE (case_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_case_members_case_id ON case_members(case_id);
CREATE INDEX IF NOT EXISTS idx_case_members_user_id ON case_members(user_id);
CREATE INDEX IF NOT EXISTS idx_case_members_role ON case_members(role);

CREATE TABLE IF NOT EXISTS case_invites (
    id VARCHAR PRIMARY KEY,
    case_id VARCHAR NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'editor',
    token VARCHAR(128) NOT NULL UNIQUE,
    invited_by VARCHAR REFERENCES users(id) ON DELETE SET NULL,
    expires_at TIMESTAMP NOT NULL,
    accepted_at TIMESTAMP,
    accepted_by_user_id VARCHAR REFERENCES users(id) ON DELETE SET NULL,
    revoked_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_invites_case_id ON case_invites(case_id);
CREATE INDEX IF NOT EXISTS idx_case_invites_email ON case_invites(email);
CREATE INDEX IF NOT EXISTS idx_case_invites_token ON case_invites(token);
CREATE INDEX IF NOT EXISTS ix_case_invites_case_email ON case_invites(case_id, email);

-- Backfill owners from cases.user_id
INSERT INTO case_members (id, case_id, user_id, role, added_by, created_at)
SELECT
    gen_random_uuid()::text,
    c.id,
    c.user_id,
    'owner',
    c.user_id,
    COALESCE(c.created_at, NOW())
FROM cases c
WHERE c.user_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM case_members m
      WHERE m.case_id = c.id AND m.user_id = c.user_id
  );
