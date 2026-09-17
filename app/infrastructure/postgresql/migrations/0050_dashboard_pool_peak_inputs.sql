-- Expose only safe pool-level change points to the Python peak calculator.
-- Preserve the existing simultaneous portfolio totals and private source rows.
DO $$
DECLARE definition text;
BEGIN
    SELECT pg_get_functiondef('eppm.dashboard_resource_breakdown_scoped(bigint[],date,text,bigint,text,text[],bigint[])'::regprocedure)
        INTO definition;
    definition := replace(definition, '''peak_days'',jsonb_build_object(',
        '''pool_days'',(SELECT coalesce(jsonb_agg(jsonb_build_array(pool_id,day,demand,capacity) ORDER BY day,pool_id),''[]''::jsonb) FROM comparisons),
        ''pool_staffing'',(SELECT coalesce(jsonb_agg(jsonb_build_array(pool_id,base,calendar)),''[]''::jsonb) FROM staffing),
        ''peak_days'',jsonb_build_object(');
    EXECUTE definition;
END $$;
