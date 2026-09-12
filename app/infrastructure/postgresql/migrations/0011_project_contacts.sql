-- Only current assignments in an actor-visible project expose occupant phones.
-- General function selectors continue to use the minimal employee-name directory.
CREATE FUNCTION eppm.project_contacts(requested_project bigint)
RETURNS TABLE(id bigint, role_id bigint, function_id bigint, function_name text,
              person text, mobile text, landline text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
    WITH visible AS MATERIALIZED (
        SELECT c.id,c.role_id,c.function_id FROM eppm.project_contact c
        WHERE c.project_id=requested_project
          AND c.project_id IN (SELECT unnest(eppm.permission_projects('project.read')))
    ), occupants AS (
        SELECT e.function_id,
            string_agg(trim(e.firstname || ' ' || e.lastname), ', '
                ORDER BY e.lastname COLLATE "C" NULLS FIRST,e.firstname COLLATE "C" NULLS FIRST,e.employee_id) AS person,
            string_agg(NULLIF(e.mobile,''), ', '
                ORDER BY e.lastname COLLATE "C" NULLS FIRST,e.firstname COLLATE "C" NULLS FIRST,e.employee_id) AS mobile,
            string_agg(NULLIF(e.landline,''), ', '
                ORDER BY e.lastname COLLATE "C" NULLS FIRST,e.firstname COLLATE "C" NULLS FIRST,e.employee_id) AS landline
        FROM eppm.employee e
        JOIN (SELECT DISTINCT v.function_id FROM visible v) selected ON selected.function_id=e.function_id
        GROUP BY e.function_id
    )
    SELECT c.id,c.role_id,c.function_id,f.name,
           COALESCE(o.person,f.name),COALESCE(o.mobile,''),COALESCE(o.landline,'')
    FROM visible c JOIN eppm.function f ON f.function_id=c.function_id
    LEFT JOIN occupants o ON o.function_id=c.function_id
$$;
REVOKE ALL ON FUNCTION eppm.project_contacts(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.project_contacts(bigint) TO eppm_runtime;
