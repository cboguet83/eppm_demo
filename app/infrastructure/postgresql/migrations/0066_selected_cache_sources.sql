-- Bound selected planning sources before expanding dependencies. Preserve the
-- original bulk path, token envelope, signed scopes, and private helper grants.
DO $$
DECLARE definition text; body text; selected_query text; prefix text; suffix text;
BEGIN
    SELECT pg_get_functiondef('eppm.current_cache_keys(text,bigint[])'::regprocedure)
        INTO definition;
    SELECT prosrc INTO body FROM pg_proc
        WHERE oid='eppm.current_cache_keys(text,bigint[])'::regprocedure;
    prefix := split_part(body, 'RETURN QUERY', 1);
    suffix := substring(body FROM position('RETURN QUERY' IN body));
    selected_query := regexp_replace(suffix, 'END[[:space:]]*$', '');
    selected_query := substring(selected_query FROM 1 FOR position('    ), sources AS (' IN selected_query)-1)
        || $sources$    ), selected_tasks AS MATERIALIZED (
        SELECT task.* FROM entities entity
        JOIN eppm.project_task task ON task.project_id=entity.id
        JOIN eppm.project_plan plan ON plan.id=task.project_plan_id AND plan.is_current
        WHERE NOT task.is_deleted
    ), sources AS (
        SELECT task.project_id AS id,coalesce(pred.project_id,dependency.predecessor_project_id) AS project_id
        FROM selected_tasks task
        JOIN eppm.task_dependencies dependency ON dependency.task_id=task.id
        LEFT JOIN LATERAL (
            SELECT active.project_id FROM eppm.project_task original
            JOIN eppm.project_task active
                ON coalesce(active.stable_task_id,active.id)=coalesce(original.stable_task_id,original.id)
            JOIN eppm.project_plan plan ON plan.id=active.project_plan_id AND plan.is_current
            WHERE original.id=dependency.predecessor_task_id AND NOT active.is_deleted OFFSET 0
        ) pred ON true
        WHERE (dependency.predecessor_task_id IS NULL OR pred.project_id=ANY(visible))
            AND (dependency.predecessor_project_id IS NULL OR dependency.predecessor_project_id=ANY(visible))
            AND coalesce(pred.project_id,dependency.predecessor_project_id)<>task.project_id
        UNION
        SELECT task.project_id,pred.project_id
        FROM selected_tasks task
        JOIN LATERAL (
            SELECT active.project_id FROM eppm.project_task original
            JOIN eppm.project_task active
                ON coalesce(active.stable_task_id,active.id)=coalesce(original.stable_task_id,original.id)
            JOIN eppm.project_plan plan ON plan.id=active.project_plan_id AND plan.is_current
            WHERE original.id=task.predecessor_id AND NOT active.is_deleted OFFSET 0
        ) pred ON true
        WHERE pred.project_id=ANY(visible) AND pred.project_id<>task.project_id
        UNION
        SELECT entity.id,coalesce(dependency.predecessor_project_id,pred.project_id)
        FROM entities entity JOIN eppm.project_dependency dependency ON dependency.project_id=entity.id
        JOIN eppm.project_plan plan ON plan.id=dependency.project_plan_id AND plan.is_current
        LEFT JOIN LATERAL (
            SELECT active.project_id FROM eppm.project_task original
            JOIN eppm.project_task active
                ON coalesce(active.stable_task_id,active.id)=coalesce(original.stable_task_id,original.id)
            JOIN eppm.project_plan current_plan ON current_plan.id=active.project_plan_id AND current_plan.is_current
            WHERE original.id=dependency.predecessor_task_id AND NOT active.is_deleted OFFSET 0
        ) pred ON true
        WHERE coalesce(dependency.predecessor_project_id,pred.project_id)=ANY(visible)
$sources$
        || substring(selected_query FROM position('    ), source_versions AS (' IN selected_query));
    definition := replace(definition, body, prefix
        || 'IF selected_ids IS NOT NULL AND kind=''planning'' THEN '
        || selected_query || ' RETURN; END IF; ' || suffix);
    EXECUTE definition;
END $$;
