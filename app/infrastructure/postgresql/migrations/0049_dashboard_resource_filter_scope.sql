-- Retain the existing private aggregate calculation, adding bound read filters
-- chosen and validated by Python. The five-argument legacy contract is unchanged.
DO $$
DECLARE definition text;
BEGIN
    SELECT pg_get_functiondef('eppm.dashboard_resource_breakdown(bigint[],date,text,bigint,text)'::regprocedure)
        INTO definition;
    definition := regexp_replace(definition, '^CREATE OR REPLACE FUNCTION [^\n]+',
        'CREATE OR REPLACE FUNCTION eppm.dashboard_resource_breakdown_scoped(requested bigint[], effective_day date, selected_quarter text, selected_pool bigint, selected_metric text, selected_statuses text[], chart_pools bigint[])');
    definition := replace(definition, 'eppm.current_resource_pool_assignment',
        '(SELECT assignment.* FROM eppm.current_resource_pool_assignment assignment
          JOIN eppm.project project ON project.id=assignment.project_id
          WHERE (selected_statuses IS NULL OR project.status=ANY(selected_statuses))
            AND (chart_pools IS NULL OR assignment.pool_id=ANY(chart_pools)))');
    EXECUTE definition;
END $$;
REVOKE ALL ON FUNCTION eppm.dashboard_resource_breakdown_scoped(bigint[],date,text,bigint,text,text[],bigint[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.dashboard_resource_breakdown_scoped(bigint[],date,text,bigint,text,text[],bigint[]) TO eppm_runtime;
