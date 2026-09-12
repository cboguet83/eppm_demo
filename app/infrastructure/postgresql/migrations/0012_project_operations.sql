-- Bounded project-editor projections and coordination of explicit/generated IDs.
CREATE FUNCTION eppm.wbs_options(edited_project bigint DEFAULT NULL)
RETURNS TABLE(id bigint, code text, description text, available integer)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    IF edited_project IS NULL THEN
        IF NOT eppm.has_global_permission('business.manage') THEN
            PERFORM eppm.require_permission('project.create');
        END IF;
    ELSE
        PERFORM eppm.require_permission('project.read', ARRAY[edited_project]);
    END IF;
    RETURN QUERY SELECT w.id,w.code,w.description,(100-COALESCE(used.percentage,0))::integer
        FROM eppm.wbs w LEFT JOIN (
            SELECT allocation.wbs_id,sum(allocation.percentage) AS percentage FROM eppm.project_wbs allocation
            WHERE edited_project IS NULL OR allocation.project_id<>edited_project GROUP BY allocation.wbs_id
        ) used ON used.wbs_id=w.id ORDER BY w.code COLLATE "C";
END $$;

CREATE FUNCTION eppm.project_id_preview() RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE counter bigint; called boolean; largest bigint;
BEGIN
    PERFORM eppm.require_permission('project.create');
    SELECT last_value,is_called INTO counter,called FROM eppm.project_id_seq;
    SELECT COALESCE(max(id),0) INTO largest FROM eppm.project;
    RETURN greatest(largest+1,counter+CASE WHEN called THEN 1 ELSE 0 END);
END $$;

CREATE FUNCTION eppm.allocate_project_id(explicit_id bigint DEFAULT NULL) RETURNS bigint
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE counter bigint; called boolean; largest bigint;
BEGIN
    PERFORM eppm.require_permission('project.create');
    IF current_setting('transaction_isolation')<>'serializable' OR current_setting('transaction_read_only')='on' THEN
        RAISE EXCEPTION 'Project creation requires a serializable write' USING ERRCODE='25001';
    END IF;
    -- Only project identity allocation shares this lock. Ordinary project edits,
    -- unrelated catalogs and planning writes do not acquire it.
    PERFORM pg_advisory_xact_lock(hashtextextended('eppm:project-identity',0));
    SELECT last_value,is_called INTO counter,called FROM eppm.project_id_seq;
    SELECT greatest(COALESCE(max(id),0),COALESCE(explicit_id,0)) INTO largest FROM eppm.project;
    IF largest>counter OR largest=counter AND NOT called THEN
        PERFORM setval('eppm.project_id_seq',largest,true);
    END IF;
    IF explicit_id IS NOT NULL THEN RETURN explicit_id; END IF;
    RETURN nextval('eppm.project_id_seq');
END $$;

REVOKE ALL ON FUNCTION eppm.wbs_options(bigint),eppm.project_id_preview(),eppm.allocate_project_id(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.wbs_options(bigint),eppm.project_id_preview(),eppm.allocate_project_id(bigint) TO eppm_runtime;
