-- Task delivery depends on selected projects/predecessors and their assigned
-- pools' visible consumers, not on every unrelated visible project revision.
CREATE FUNCTION eppm.planning_task_source_keys(selected_ids bigint[])
RETURNS TABLE(project_id bigint, source_token text)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, eppm, pg_temp
SET plan_cache_mode = force_custom_plan AS $$
BEGIN
    IF selected_ids IS NULL OR cardinality(selected_ids) NOT BETWEEN 1 AND 25
       OR array_position(selected_ids,NULL) IS NOT NULL THEN
        RAISE EXCEPTION 'Invalid task batch' USING ERRCODE='22023';
    END IF;
    RETURN QUERY
    WITH projects AS MATERIALIZED (
        SELECT entity_id,source.source_token FROM eppm.current_cache_keys('planning',selected_ids) source
    ), assignments AS MATERIALIZED (
        SELECT DISTINCT assignment.project_id,assignment.pool_id
        FROM eppm.resource_pool_assignment assignment JOIN projects ON projects.entity_id=assignment.project_id
    ), pools AS MATERIALIZED (
        SELECT entity_id,source.source_token FROM eppm.current_cache_keys(
            'capacity',ARRAY(SELECT DISTINCT pool_id FROM assignments)) source
    ), pool_sources AS (
        SELECT assignment.project_id,jsonb_agg(jsonb_build_array(pools.entity_id,pools.source_token)
                                              ORDER BY pools.entity_id) AS sources
        FROM assignments assignment JOIN pools ON pools.entity_id=assignment.pool_id
        GROUP BY assignment.project_id
    )
    SELECT projects.entity_id,encode(eppm_crypto.digest(convert_to(jsonb_build_array(
        'planning.tasks.v1',projects.source_token,coalesce(pool_sources.sources,'[]'::jsonb)
    )::text,'UTF8'),'sha256'),'hex')
    FROM projects LEFT JOIN pool_sources ON pool_sources.project_id=projects.entity_id;
END $$;
REVOKE ALL ON FUNCTION eppm.planning_task_source_keys(bigint[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.planning_task_source_keys(bigint[]) TO eppm_runtime;
