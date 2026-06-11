-- Migration: Drop legacy Workflow tables
-- Feature removed; tables are no longer used by application code.
-- Safe order: child tables first (workflow_steps → workflow_executions → definitions/templates).

DROP TABLE IF EXISTS workflow_steps CASCADE;
DROP TABLE IF EXISTS workflow_executions CASCADE;
DROP TABLE IF EXISTS workflow_definitions CASCADE;
DROP TABLE IF EXISTS workflow_templates CASCADE;
