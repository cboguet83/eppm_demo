-- Repair the row sources missed by the relational-plan migration. Preserve the
-- existing aggregate/privacy boundary and all resource calculation semantics.
DO $$
DECLARE definition text;
BEGIN
    SELECT pg_get_functiondef('eppm.dashboard_resource_breakdown(bigint[],date,text,bigint,text)'::regprocedure)
        INTO definition;
    definition := replace(definition, 'eppm.resource_pool_assignment', 'eppm.current_resource_pool_assignment');
    -- This definer aggregate needs hidden competitors' dates, but must never
    -- return their tasks. The public current-task view intentionally redacts them.
    definition := replace(definition, 'eppm.project_task',
        '(SELECT * FROM eppm.project_task WHERE NOT is_deleted AND project_plan_id IN (SELECT id FROM eppm.project_plan WHERE is_current))');
    -- selected_pool already has an authorization check; restrict the input rows
    -- after that check for chart reads (no selected quarter), retaining each
    -- pool's own peaks without changing the consumer drill-through contract.
    definition := replace(definition, 'IF cardinality(selected_pools)=0 THEN',
        'IF selected_pool IS NOT NULL AND selected_quarter IS NULL THEN selected_pools := ARRAY[selected_pool]; END IF;
    IF cardinality(selected_pools)=0 THEN');
    EXECUTE definition;
END $$;
