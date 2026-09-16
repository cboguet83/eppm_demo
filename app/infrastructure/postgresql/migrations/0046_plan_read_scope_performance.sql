-- Evaluate signed permission scopes once per statement, not once per task.
-- Keep the existing security barriers, endpoint redaction and RLS semantics.
SET LOCAL search_path = pg_catalog;
DO $$
DECLARE target text; definition text;
BEGIN
    FOREACH target IN ARRAY ARRAY['current_project_task','plan_task_edit_access','plan_row_dependencies'] LOOP
        SELECT pg_get_viewdef(format('eppm.%I',target)::regclass,true) INTO definition;
        definition := replace(definition,
            'eppm.permission_projects(''project.read''::text)',
            '((SELECT eppm.permission_projects(''project.read''::text))::bigint[])');
        definition := replace(definition,
            'eppm.permission_projects(''project.edit''::text)',
            '((SELECT eppm.permission_projects(''project.edit''::text))::bigint[])');
        EXECUTE format('CREATE OR REPLACE VIEW eppm.%I AS %s',target,definition);
    END LOOP;
END $$;

ALTER POLICY plan_revision_read ON eppm.project_cache_revision
    USING(project_id IN (SELECT unnest(eppm.permission_projects('project.read'))));

-- Resolve primary links in one relational join. A correlated lookup through
-- the edit-access view used to repeat its scope/graph work for every task.
CREATE OR REPLACE VIEW eppm.current_project_task WITH(security_barrier=true) AS
    SELECT t.id,t.project_id,t.task_name,t.phase,t.start_date,t.end_date,
        t.progress_pct,t.description,
        CASE WHEN NOT (SELECT eppm.runtime_session()) THEN t.predecessor_id
            WHEN original.project_id IN (SELECT unnest(CASE WHEN eppm.runtime_session()
                THEN eppm.permission_projects('project.read') ELSE '{}'::bigint[] END))
                THEN coalesce(active.id,t.predecessor_id) END AS predecessor_id,
        t.project_plan_id,t.stable_task_id,t.is_deleted
    FROM eppm.project_task t
    LEFT JOIN eppm.project_task original ON original.id=t.predecessor_id
    LEFT JOIN eppm.project_task active
        ON coalesce(active.stable_task_id,active.id)=coalesce(original.stable_task_id,original.id)
        AND NOT active.is_deleted
        AND active.project_plan_id IN (SELECT id FROM eppm.project_plan WHERE is_current)
    WHERE NOT t.is_deleted
        AND t.project_plan_id IN (SELECT id FROM eppm.project_plan WHERE is_current)
        AND (NOT (SELECT eppm.runtime_session())
            OR t.project_id IN (SELECT unnest(CASE WHEN eppm.runtime_session()
                THEN eppm.permission_projects('project.read') ELSE '{}'::bigint[] END)));
