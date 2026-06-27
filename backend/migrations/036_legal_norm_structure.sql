-- Структурный скелет НПА: типы узлов, иерархия CHILD_OF, порядок NEXT.

ALTER TABLE legal_norm_nodes
    ADD COLUMN IF NOT EXISTS node_type TEXT NOT NULL DEFAULT 'clause';

ALTER TABLE legal_norm_nodes
    ADD COLUMN IF NOT EXISTS parent_norm_key TEXT;

ALTER TABLE legal_norm_nodes
    ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '';

ALTER TABLE legal_norm_nodes
    ADD COLUMN IF NOT EXISTS chapter_ref TEXT NOT NULL DEFAULT '';

ALTER TABLE legal_norm_nodes
    ALTER COLUMN chunk_id DROP NOT NULL;

UPDATE legal_norm_nodes
SET node_type = CASE
    WHEN clause_ref = '' OR clause_ref IS NULL THEN 'article'
    ELSE 'clause'
END
WHERE node_type = 'clause' AND chunk_id IS NOT NULL;

ALTER TABLE legal_norm_graph_edges
    DROP CONSTRAINT IF EXISTS legal_norm_graph_edges_edge_type_check;

ALTER TABLE legal_norm_graph_edges
    ADD CONSTRAINT legal_norm_graph_edges_edge_type_check
    CHECK (edge_type IN (
        'REFERENCES', 'FORWARD_TO', 'DEVELOPS', 'EXCEPTS', 'CHILD_OF', 'NEXT'
    ));

CREATE INDEX IF NOT EXISTS idx_legal_norm_nodes_parent
    ON legal_norm_nodes(parent_norm_key);

CREATE INDEX IF NOT EXISTS idx_legal_norm_nodes_type
    ON legal_norm_nodes(instrument_id, node_type);

CREATE INDEX IF NOT EXISTS idx_legal_norm_edges_child_of
    ON legal_norm_graph_edges(target_norm_key, edge_type)
    WHERE edge_type = 'CHILD_OF';
