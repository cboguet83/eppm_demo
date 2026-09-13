-- Every child row in these tables has a non-null project FK. A global reader
-- therefore needs no enumeration of all mutable projects to read one child.
-- Match the project's existing 0022 policy; scoped visibility and the separate
-- old/new-owner, protected-property and audit guards continue to apply.
-- Keep scope resolution inside a scalar InitPlan. unnest(stable_function())
-- can execute the function during row-count estimation, before the global
-- branch short-circuits execution, acquiring predicates over all projects.
DO $$
DECLARE target text; policy_name text; owner_column text;
BEGIN
    FOREACH target IN ARRAY ARRAY[
        'project', 'project_task', 'project_wbs', 'project_link', 'project_contact',
        'project_log_event', 'project_property_value', 'project_property_value_item',
        'project_tag', 'resource_pool_assignment'
    ] LOOP
        owner_column := CASE WHEN target = 'project' THEN 'id' ELSE 'project_id' END;
        FOREACH policy_name IN ARRAY ARRAY['business_select', 'business_update', 'business_delete'] LOOP
            EXECUTE format('ALTER POLICY %I ON eppm.%I USING ('
                || '(SELECT eppm.has_global_permission(''project.read''))'
                || ' OR %I = ANY ((SELECT eppm.permission_projects(''project.read''))::bigint[]))',
                policy_name, target, owner_column);
        END LOOP;
    END LOOP;
END $$;
