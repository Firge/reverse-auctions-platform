CREATE TABLE IF NOT EXISTS catalog_nodes (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_id BIGINT REFERENCES catalog_nodes(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS catalog_nodes_unique_idx
    ON catalog_nodes (kind, name, COALESCE(parent_id, 0));

CREATE TABLE IF NOT EXISTS catalog_sources (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS catalog_items (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    price_release NUMERIC(14,2),
    price_estimate NUMERIC(14,2),
    node_id BIGINT REFERENCES catalog_nodes(id),
    source_id BIGINT REFERENCES catalog_sources(id) NOT NULL
);

CREATE INDEX IF NOT EXISTS catalog_nodes_parent_idx ON catalog_nodes(parent_id);
CREATE INDEX IF NOT EXISTS catalog_items_code_idx ON catalog_items(code);
