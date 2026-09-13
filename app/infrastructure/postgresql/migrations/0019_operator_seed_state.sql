-- Operator seed markers preserve intentionally edited or emptied reference data.
-- They are neither schema migrations nor runtime business cache revisions.
CREATE TABLE eppm.operator_seed_state (
    catalog text PRIMARY KEY CHECK (catalog IN ('reference', 'demo')),
    installed_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON TABLE eppm.operator_seed_state FROM PUBLIC, eppm_runtime;
