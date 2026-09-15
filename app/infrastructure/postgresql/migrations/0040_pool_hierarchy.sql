-- Business validation, group conversion and aggregation run in Python.
ALTER TABLE eppm.resource_pool ADD COLUMN parent_pool_id bigint
    REFERENCES eppm.resource_pool(id) ON DELETE RESTRICT;
ALTER TABLE eppm.resource_pool ADD CONSTRAINT pool_parent_not_self
    CHECK (parent_pool_id IS DISTINCT FROM id);
CREATE INDEX resource_pool_parent ON eppm.resource_pool(parent_pool_id);

-- An authorization projection exposes only pool IDs to shared administrators.
-- The view owner can see hidden assignments; no project, task or demand data
-- is disclosed. Python uses this set to enforce the leaf-to-container rule.
CREATE VIEW eppm.assigned_pool_ids WITH (security_barrier=true) AS
    SELECT DISTINCT pool_id FROM eppm.resource_pool_assignment
    WHERE (SELECT eppm.has_global_permission('business.manage'));
REVOKE ALL ON eppm.assigned_pool_ids FROM PUBLIC;
GRANT SELECT ON eppm.assigned_pool_ids TO eppm_runtime;
