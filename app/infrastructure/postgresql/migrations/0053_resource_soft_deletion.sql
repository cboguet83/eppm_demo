-- Preserve identities, mappings and history when organization resources are deleted.
ALTER TABLE eppm.team ADD COLUMN deleted_flag boolean NOT NULL DEFAULT false;
ALTER TABLE eppm.function ADD COLUMN deleted_flag boolean NOT NULL DEFAULT false;
ALTER TABLE eppm.employee ADD COLUMN deleted_flag boolean NOT NULL DEFAULT false;
ALTER TABLE eppm.resource_pool ADD COLUMN deleted_flag boolean NOT NULL DEFAULT false;
ALTER TABLE eppm.function_type ADD COLUMN deleted_flag boolean NOT NULL DEFAULT false;
ALTER TABLE eppm.hierarchy_type ADD COLUMN deleted_flag boolean NOT NULL DEFAULT false;

-- Read projections retain the caller's existing row-level access controls.
CREATE VIEW eppm.active_team WITH (security_invoker = true) AS
    SELECT * FROM eppm.team WHERE NOT deleted_flag;
CREATE VIEW eppm.active_function WITH (security_invoker = true) AS
    SELECT * FROM eppm.function WHERE NOT deleted_flag;
CREATE VIEW eppm.active_employee WITH (security_invoker = true) AS
    SELECT * FROM eppm.employee WHERE NOT deleted_flag;
CREATE VIEW eppm.active_resource_pool WITH (security_invoker = true) AS
    SELECT * FROM eppm.resource_pool WHERE NOT deleted_flag;
CREATE VIEW eppm.active_function_type WITH (security_invoker = true) AS
    SELECT * FROM eppm.function_type WHERE NOT deleted_flag;
CREATE VIEW eppm.active_hierarchy_type WITH (security_invoker = true) AS
    SELECT * FROM eppm.hierarchy_type WHERE NOT deleted_flag;
GRANT SELECT ON eppm.active_team, eppm.active_function, eppm.active_employee,
    eppm.active_resource_pool, eppm.active_function_type, eppm.active_hierarchy_type
    TO eppm_runtime;

CREATE VIEW eppm.active_pool_assignment WITH (security_invoker = true) AS
    SELECT a.* FROM eppm.current_resource_pool_assignment a
    JOIN eppm.active_resource_pool p ON p.id=a.pool_id;
GRANT SELECT ON eppm.active_pool_assignment TO eppm_runtime;

CREATE VIEW eppm.active_team_function WITH (security_invoker = true) AS
    SELECT tf.* FROM eppm.team_function tf
    JOIN eppm.active_team t ON t.team_id=tf.team_id
    JOIN eppm.active_function f ON f.function_id=tf.function_id;
GRANT SELECT ON eppm.active_team_function TO eppm_runtime;

CREATE VIEW eppm.active_pool_mapping WITH (security_invoker = true) AS
    SELECT m.* FROM eppm.resource_pool_mapping m
    JOIN eppm.active_resource_pool p ON p.id=m.pool_id
    WHERE (m.target_type='team' AND EXISTS(SELECT 1 FROM eppm.active_team t WHERE t.team_id=m.target_id))
       OR (m.target_type='function' AND EXISTS(SELECT 1 FROM eppm.active_function f WHERE f.function_id=m.target_id))
       OR (m.target_type='employee' AND EXISTS(SELECT 1 FROM eppm.active_employee e WHERE e.employee_id=m.target_id));
GRANT SELECT ON eppm.active_pool_mapping TO eppm_runtime;

-- Keep existing authorization and aggregate contracts; filter their source rows.
DO $$
DECLARE item record; definition text;
BEGIN
    FOR item IN SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='eppm' AND p.proname IN (
            'capacity_contributions','pool_staffing','pool_effective_capacity',
            'dashboard_resources','dashboard_resource_breakdown','dashboard_resource_breakdown_scoped',
            'current_cache_keys','display_cache_revisions','portfolio_cache_revision','planning_task_source_keys')
    LOOP
        definition := pg_get_functiondef(item.oid);
        definition := regexp_replace(definition,
            '(FROM|JOIN) eppm\.(team|function|employee|resource_pool)\M',
            '\1 eppm.active_\2', 'g');
        definition := replace(definition, 'LEFT JOIN eppm.active_team t', 'JOIN eppm.active_team t');
        definition := replace(definition, 'FROM eppm.current_resource_pool_assignment',
            'FROM eppm.active_pool_assignment');
        definition := replace(definition, 'FROM eppm.resource_pool_mapping', 'FROM eppm.active_pool_mapping');
        EXECUTE definition;
    END LOOP;
END $$;

CREATE OR REPLACE VIEW eppm.employee_name_directory WITH (security_barrier = true) AS
    SELECT function_id,firstname,lastname FROM eppm.employee
    WHERE NOT deleted_flag AND (SELECT eppm.has_business_read());
CREATE OR REPLACE VIEW eppm.project_manager_directory WITH (security_barrier = true) AS
    SELECT f.function_id,coalesce((SELECT nullif(trim(e.firstname || ' ' || e.lastname),'')
        FROM eppm.employee e WHERE NOT e.deleted_flag AND e.function_id=f.function_id AND trim(e.firstname || e.lastname)<>''
        ORDER BY e.lastname,e.firstname,e.employee_id LIMIT 1),nullif(f.name,''),'—') AS label
    FROM eppm.function f WHERE NOT f.deleted_flag AND (SELECT eppm.has_business_read());

UPDATE eppm.catalog_cache_revision SET revision=revision+1;
