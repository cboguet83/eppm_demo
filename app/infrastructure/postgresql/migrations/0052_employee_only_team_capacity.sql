-- Team mappings count actual employees, never vacant function FTE.
DO $$
DECLARE definition text;
BEGIN
    SELECT pg_get_functiondef('eppm.capacity_contributions(bigint[])'::regprocedure)
        INTO definition;
    definition := replace(definition,
        'FROM team_members m LEFT JOIN eppm.employee e ON e.function_id=m.function_id',
        'FROM team_members m JOIN eppm.employee e ON e.function_id=m.function_id');
    EXECUTE definition;

    -- A valid team mapping still selects staffing capacity when it has no employees.
    SELECT pg_get_functiondef('eppm.pool_staffing(bigint[])'::regprocedure)
        INTO definition;
    definition := replace(definition, 'coalesce(t.assigned,0.0),t.pool_id IS NOT NULL,',
        'coalesce(t.assigned,0.0),(t.pool_id IS NOT NULL OR EXISTS (
            SELECT 1 FROM eppm.resource_pool_mapping mapping
            JOIN eppm.team team ON team.team_id=mapping.target_id
            WHERE mapping.pool_id=p.id AND mapping.target_type=''team'')),');
    EXECUTE definition;
END $$;

UPDATE eppm.catalog_cache_revision SET revision = revision + 1;
