-- Remove the obsolete badge field, retaining employee IDs and all mappings.
-- Recreate the dependent read views explicitly to preserve their access policy.
DROP VIEW eppm.active_pool_mapping;
DROP VIEW eppm.active_employee_function;
DROP VIEW eppm.active_employee;
ALTER TABLE eppm.employee DROP COLUMN employee_code;

CREATE VIEW eppm.active_employee WITH (security_invoker=true) AS
    SELECT * FROM eppm.employee WHERE NOT deleted_flag;
CREATE VIEW eppm.active_employee_function WITH (security_invoker=true) AS
    SELECT ef.* FROM eppm.employee_function ef
    JOIN eppm.active_employee e ON e.employee_id=ef.employee_id
    JOIN eppm.active_function f ON f.function_id=ef.function_id;
CREATE VIEW eppm.active_pool_mapping WITH (security_invoker=true) AS
    SELECT m.* FROM eppm.resource_pool_mapping m
    JOIN eppm.active_resource_pool p ON p.id=m.pool_id
    WHERE (m.target_type='team' AND EXISTS(SELECT 1 FROM eppm.active_team t WHERE t.team_id=m.target_id))
       OR (m.target_type='function' AND EXISTS(SELECT 1 FROM eppm.active_function f WHERE f.function_id=m.target_id))
       OR (m.target_type='employee' AND EXISTS(SELECT 1 FROM eppm.active_employee e WHERE e.employee_id=m.target_id));
GRANT SELECT ON eppm.active_employee, eppm.active_employee_function, eppm.active_pool_mapping TO eppm_runtime;
UPDATE eppm.catalog_cache_revision SET revision=revision+1;
