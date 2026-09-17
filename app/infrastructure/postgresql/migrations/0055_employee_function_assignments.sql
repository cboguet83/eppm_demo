-- Existing links become explicit 100% assignments, including retained records.
ALTER INDEX eppm.employee_function RENAME TO employee_legacy_function_idx;
CREATE TABLE eppm.employee_function (
    employee_id bigint NOT NULL REFERENCES eppm.employee(employee_id) ON DELETE RESTRICT,
    function_id bigint NOT NULL REFERENCES eppm.function(function_id) ON DELETE RESTRICT,
    allocation_pct double precision NOT NULL DEFAULT 100 CHECK (allocation_pct BETWEEN 0 AND 100),
    PRIMARY KEY(employee_id,function_id)
);
INSERT INTO eppm.employee_function(employee_id,function_id)
    SELECT employee_id,function_id FROM eppm.employee WHERE function_id IS NOT NULL;
CREATE INDEX employee_function_by_function ON eppm.employee_function(function_id);
COMMENT ON COLUMN eppm.employee.function_id IS 'Legacy import field. Application membership uses employee_function exclusively.';
ALTER TABLE eppm.employee_function ENABLE ROW LEVEL SECURITY;
ALTER TABLE eppm.employee_function FORCE ROW LEVEL SECURITY;
CREATE POLICY shared_access ON eppm.employee_function TO eppm_runtime
    USING ((SELECT eppm.has_global_permission('business.manage')))
    WITH CHECK ((SELECT eppm.has_global_permission('business.manage')));
CREATE TRIGGER authorize_business BEFORE INSERT OR UPDATE OR DELETE ON eppm.employee_function
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_business_write('shared');
CREATE TRIGGER invalidate_capacity AFTER INSERT OR UPDATE OR DELETE ON eppm.employee_function
    FOR EACH ROW EXECUTE FUNCTION eppm.invalidate_business_caches('catalog');
GRANT SELECT,INSERT,UPDATE,DELETE ON eppm.employee_function TO eppm_runtime;
CREATE VIEW eppm.active_employee_function WITH (security_invoker=true) AS
    SELECT ef.* FROM eppm.employee_function ef
    JOIN eppm.active_employee e ON e.employee_id=ef.employee_id
    JOIN eppm.active_function f ON f.function_id=ef.function_id;
GRANT SELECT ON eppm.active_employee_function TO eppm_runtime;
CREATE OR REPLACE VIEW eppm.employee_name_directory WITH (security_barrier=true) AS
    SELECT ef.function_id,e.firstname,e.lastname FROM eppm.employee_function ef
    JOIN eppm.employee e ON e.employee_id=ef.employee_id AND NOT e.deleted_flag
    JOIN eppm.function f ON f.function_id=ef.function_id AND NOT f.deleted_flag
    WHERE (SELECT eppm.has_business_read());
CREATE OR REPLACE VIEW eppm.project_manager_directory WITH (security_barrier=true) AS
    SELECT f.function_id,coalesce((SELECT nullif(trim(e.firstname || ' ' || e.lastname),'')
        FROM eppm.employee_function ef JOIN eppm.employee e ON e.employee_id=ef.employee_id
        WHERE NOT e.deleted_flag AND ef.function_id=f.function_id AND trim(e.firstname || e.lastname)<>''
        ORDER BY e.lastname,e.firstname,e.employee_id LIMIT 1),nullif(f.name,''),'—') AS label
    FROM eppm.function f WHERE NOT f.deleted_flag AND (SELECT eppm.has_business_read());
DO $$
DECLARE definition text;
BEGIN
    SELECT pg_get_functiondef('eppm.project_contacts(bigint)'::regprocedure) INTO definition;
    definition := replace(definition,'FROM eppm.employee e','FROM eppm.active_employee e');
    definition := replace(definition,'FROM eppm.active_employee e',
        'FROM eppm.active_employee e JOIN eppm.active_employee_function ef ON ef.employee_id=e.employee_id');
    definition := replace(definition,'e.function_id','ef.function_id');
    EXECUTE definition;
END $$;

-- Python publishes staffing in the same transaction as each staffing change.
-- The existing reader remains an authorization boundary, not a calculator.
CREATE TABLE eppm.pool_staffing_projection (
    pool_id bigint PRIMARY KEY REFERENCES eppm.resource_pool(id) ON DELETE CASCADE,
    assigned_capacity_fte double precision NOT NULL,
    has_assigned_resources boolean NOT NULL,
    daily_assigned_capacity jsonb NOT NULL,
    contributing_resources jsonb NOT NULL
);
ALTER TABLE eppm.pool_staffing_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE eppm.pool_staffing_projection FORCE ROW LEVEL SECURITY;
CREATE POLICY shared_access ON eppm.pool_staffing_projection TO eppm_runtime
    USING ((SELECT eppm.has_global_permission('business.manage')))
    WITH CHECK ((SELECT eppm.has_global_permission('business.manage')));
GRANT SELECT,INSERT,UPDATE,DELETE ON eppm.pool_staffing_projection TO eppm_runtime;

CREATE OR REPLACE FUNCTION eppm.pool_staffing(requested_pools bigint[])
RETURNS TABLE(pool_id bigint, assigned_capacity_fte double precision, has_assigned_resources boolean,
              daily_assigned_capacity jsonb, contributing_resources jsonb)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,eppm,pg_temp AS $$
BEGIN
    IF NOT eppm.has_business_read() THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    RETURN QUERY SELECT p.id,coalesce(s.assigned_capacity_fte,0),coalesce(s.has_assigned_resources,false),
        coalesce(s.daily_assigned_capacity,'{}'::jsonb),
        CASE WHEN eppm.has_global_permission('business.manage') THEN coalesce(s.contributing_resources,'[]'::jsonb)
             ELSE '[]'::jsonb END
        FROM eppm.active_resource_pool p LEFT JOIN eppm.pool_staffing_projection s ON s.pool_id=p.id
        WHERE p.id=ANY(requested_pools) ORDER BY p.id;
END $$;
UPDATE eppm.catalog_cache_revision SET revision=revision+1;
