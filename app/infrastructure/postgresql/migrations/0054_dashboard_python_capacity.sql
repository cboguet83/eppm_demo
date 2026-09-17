-- Transport Python-calculated capacities into the existing private demand reader.
-- Capacity source selection and exception rules remain in the Python domain.
DO $$
DECLARE definition text;
BEGIN
    SELECT pg_get_functiondef('eppm.dashboard_resource_breakdown_scoped(bigint[],date,text,bigint,text,text[],bigint[])'::regprocedure)
        INTO definition;
    IF position('SELECT * FROM eppm.pool_effective_capacity(selected_pools)' IN definition)=0 THEN
        RAISE EXCEPTION 'Dashboard capacity input boundary was not found';
    END IF;
    definition := replace(definition, 'eppm.dashboard_resource_breakdown_scoped(',
        'eppm.dashboard_resource_breakdown_with_capacity(capacity_inputs jsonb, ');
    definition := replace(definition, 'SELECT * FROM eppm.pool_effective_capacity(selected_pools)',
        'SELECT c.pool_id,c.base,c.calendar FROM jsonb_to_recordset(capacity_inputs)
            AS c(pool_id bigint,base double precision,calendar jsonb)
            WHERE c.pool_id=ANY(selected_pools)');
    EXECUTE definition;
END $$;
REVOKE ALL ON FUNCTION eppm.dashboard_resource_breakdown_with_capacity(jsonb,bigint[],date,text,bigint,text,text[],bigint[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.dashboard_resource_breakdown_with_capacity(jsonb,bigint[],date,text,bigint,text,text[],bigint[]) TO eppm_runtime;
