-- Expose only anonymous allocation facts; availability is calculated in Python.
DROP FUNCTION eppm.wbs_options(bigint);
CREATE FUNCTION eppm.wbs_allocation_facts(edited_project bigint DEFAULT NULL)
RETURNS TABLE(id bigint, code text, description text, percentage numeric, status text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    IF edited_project IS NULL THEN
        IF NOT eppm.has_global_permission('business.manage') THEN
            PERFORM eppm.require_permission('project.create');
        END IF;
    ELSE
        PERFORM eppm.require_permission('project.read', ARRAY[edited_project]);
    END IF;
    RETURN QUERY SELECT w.id,w.code,w.description,a.percentage,p.status
        FROM eppm.wbs w
        LEFT JOIN eppm.project_wbs a ON a.wbs_id=w.id
            AND (edited_project IS NULL OR a.project_id<>edited_project)
        LEFT JOIN eppm.project p ON p.id=a.project_id
        ORDER BY w.code COLLATE "C";
END $$;
REVOKE ALL ON FUNCTION eppm.wbs_allocation_facts(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.wbs_allocation_facts(bigint) TO eppm_runtime;

-- Retain the existing database integrity backstop for direct SQL writes.
CREATE OR REPLACE FUNCTION eppm.guard_wbs_total() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
DECLARE wbs_key bigint;
BEGIN
    FOR wbs_key IN SELECT DISTINCT value FROM unnest(ARRAY[NEW.wbs_id, OLD.wbs_id]) value
        WHERE value IS NOT NULL ORDER BY value
    LOOP
        PERFORM pg_advisory_xact_lock(hashtextextended('eppm:wbs:' || wbs_key, 0));
    END LOOP;
    IF (SELECT status FROM eppm.project WHERE id=NEW.project_id) <> 'Cancelled'
        AND NEW.percentage + (SELECT coalesce(sum(a.percentage), 0) FROM eppm.project_wbs a
            JOIN eppm.project p ON p.id=a.project_id
            WHERE a.wbs_id = NEW.wbs_id AND p.status <> 'Cancelled'
                AND (TG_OP <> 'UPDATE' OR (a.project_id, a.wbs_id) <> (OLD.project_id, OLD.wbs_id))) > 100 THEN
        RAISE EXCEPTION 'WBS total allocation cannot exceed 100%%' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
