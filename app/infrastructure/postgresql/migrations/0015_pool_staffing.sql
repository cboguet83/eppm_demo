-- Exact three-decimal rounding of the existing binary64 capacity calculations.
-- PostgreSQL's float-to-numeric cast loses the low bits that distinguish some
-- historical half-millifte cases. Decode the finite float before rounding ties
-- to even; this helper is private to the aggregate implementation.
CREATE FUNCTION eppm.capacity_round3(value double precision) RETURNS double precision
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE
    bytes bytea := float8send(abs(value));
    exponent integer := ((get_byte(bytes,0) & 127) * 16 + get_byte(bytes,1) / 16) - 1075;
    significand bigint := get_byte(bytes,1) & 15;
    exact_value numeric;
    integral numeric;
    fraction numeric;
BEGIN
    IF abs(value) >= 4503599627370496 THEN RETURN value; END IF;
    IF exponent < -64 THEN RETURN 0.0; END IF;
    FOR position IN 2..7 LOOP significand := significand * 256 + get_byte(bytes,position); END LOOP;
    significand := significand + 4503599627370496;
    exact_value := significand::numeric * power(5::numeric,-exponent) * ('1e' || exponent)::numeric * 1000;
    integral := trunc(exact_value);
    fraction := exact_value - integral;
    IF fraction > 0.5 OR (fraction = 0.5 AND mod(integral,2) = 1) THEN integral := integral + 1; END IF;
    RETURN (CASE WHEN value < 0 THEN -integral ELSE integral END / 1000)::double precision;
END $$;
REVOKE ALL ON FUNCTION eppm.capacity_round3(double precision) FROM PUBLIC, eppm_runtime;

-- Resolve occupied/vacant functions, historical implicit team membership and
-- direct employee overrides once per requested batch. Private employee rows
-- never become a runtime-selectable view or directly callable function.
CREATE FUNCTION eppm.capacity_contributions(requested_pools bigint[])
RETURNS TABLE(pool_id bigint, resource_type text, resource_id bigint,
              function_id bigint, function_name text, employee_id bigint, employee_name text,
              nominal_fte double precision, effective_allocation_pct double precision,
              effective_fte double precision, source_type text, source_name text, is_deduplicated boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
    WITH mappings AS MATERIALIZED (
        SELECT m.* FROM eppm.resource_pool_mapping m WHERE m.pool_id=ANY(requested_pools)
    ), team_members AS (
        SELECT m.pool_id,m.id,m.allocation_pct,coalesce(t.team_name,'Team #' || m.target_id) AS source_name,
               f.function_id
        FROM mappings m LEFT JOIN eppm.team t ON t.team_id=m.target_id
        CROSS JOIN LATERAL (
            SELECT tf.function_id FROM eppm.team_function tf WHERE tf.team_id=m.target_id
            UNION SELECT t.manager_function_id
            UNION SELECT t.leader_function_id
            UNION SELECT f.function_id FROM eppm.function f
                WHERE f.manager_function_id=t.manager_function_id AND
                    (SELECT count(*) FROM eppm.team_function tf WHERE tf.team_id=m.target_id)
                    + (t.manager_function_id IS NOT NULL)::integer + (t.leader_function_id IS NOT NULL)::integer <= 2
        ) member JOIN eppm.function f ON f.function_id=member.function_id
        WHERE m.target_type='team'
    ), candidates AS (
        SELECT m.pool_id,m.id,m.allocation_pct,m.source_name,0 AS priority,
               CASE WHEN e.employee_id IS NULL THEN 'function' ELSE 'employee' END AS kind,
               coalesce(e.employee_id,m.function_id) AS identity
        FROM team_members m LEFT JOIN eppm.employee e ON e.function_id=m.function_id
        UNION ALL
        SELECT m.pool_id,m.id,m.allocation_pct,'Direct Function Mapping',1,
               CASE WHEN e.employee_id IS NULL THEN 'function' ELSE 'employee' END,
               coalesce(e.employee_id,f.function_id)
        FROM mappings m JOIN eppm.function f ON f.function_id=m.target_id
        LEFT JOIN eppm.employee e ON e.function_id=f.function_id WHERE m.target_type='function'
        UNION ALL
        SELECT m.pool_id,m.id,m.allocation_pct,'Direct Employee Mapping',2,'employee',e.employee_id
        FROM mappings m JOIN eppm.employee e ON e.employee_id=m.target_id WHERE m.target_type='employee'
    ), ranked AS (
        SELECT c.*,row_number() OVER (
            PARTITION BY c.pool_id,c.kind,c.identity ORDER BY c.priority DESC,c.allocation_pct DESC,c.id
        ) AS selected,count(*) OVER (PARTITION BY c.pool_id,c.kind,c.identity) AS occurrences
        FROM candidates c
    ), chosen AS (
        SELECT c.*,coalesce(e.function_id,CASE WHEN c.kind='function' THEN c.identity ELSE 0 END) AS function_key,
               e.employee_id,trim(e.firstname) || ' ' || trim(e.lastname) AS employee_name,
               CASE WHEN e.employee_id IS NOT NULL THEN e.occupation_percentage
                    ELSE coalesce(f.fte_percentage,100)::double precision END / 100.0::double precision AS nominal
        FROM ranked c LEFT JOIN eppm.employee e ON c.kind='employee' AND e.employee_id=c.identity
        LEFT JOIN eppm.function f ON c.kind='function' AND f.function_id=c.identity WHERE c.selected=1
    )
    SELECT c.pool_id,c.kind,c.identity,c.function_key,coalesce(f.name,'Unassigned function'),
           c.employee_id,trim(c.employee_name),c.nominal,c.allocation_pct,
           eppm.capacity_round3(c.nominal * (c.allocation_pct / 100.0::double precision)),
           CASE WHEN c.priority=0 THEN 'team' ELSE 'direct' END,c.source_name,c.occurrences>1
    FROM chosen c LEFT JOIN eppm.function f ON f.function_id=c.function_key
    ORDER BY c.pool_id,c.kind COLLATE "C",c.identity
$$;
REVOKE ALL ON FUNCTION eppm.capacity_contributions(bigint[]) FROM PUBLIC, eppm_runtime;

-- All business readers receive pool totals and daily availability. Only current
-- shared administrators receive individual contributions. No employee phone,
-- email, code, calendar reason or exception identity is returned by this API.
CREATE FUNCTION eppm.pool_staffing(requested_pools bigint[])
RETURNS TABLE(pool_id bigint, assigned_capacity_fte double precision, has_assigned_resources boolean,
              daily_assigned_capacity jsonb, contributing_resources jsonb)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE
    show_people boolean;
BEGIN
    IF NOT eppm.has_business_read() THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    show_people := eppm.has_global_permission('business.manage');
    RETURN QUERY
    WITH contributions AS MATERIALIZED (SELECT * FROM eppm.capacity_contributions(requested_pools)),
    totals AS MATERIALIZED (
        SELECT c.pool_id,eppm.capacity_round3(sum(c.effective_fte ORDER BY c.resource_type COLLATE "C",c.resource_id)) AS assigned,
               CASE WHEN show_people THEN jsonb_agg(to_jsonb(c) - 'pool_id' - 'resource_id'
                    ORDER BY c.resource_type COLLATE "C",c.resource_id) ELSE '[]'::jsonb END AS people
        FROM contributions c GROUP BY c.pool_id
    ), deltas AS (
        SELECT c.pool_id,exception.start_date + series.offset_days AS day,
               sum(((exception.occupation_percentage - e.occupation_percentage) / 100.0::double precision)
                   * (c.effective_allocation_pct / 100.0::double precision)
                   ORDER BY exception.start_date DESC,exception.end_date DESC,exception.exception_id DESC) AS change
        FROM contributions c JOIN eppm.employee e ON e.employee_id=c.employee_id
        JOIN eppm.employee_calendar_exception exception ON exception.employee_id=e.employee_id
        CROSS JOIN LATERAL generate_series(0,least(exception.end_date-exception.start_date,9124)) AS series(offset_days)
        GROUP BY c.pool_id,exception.start_date + series.offset_days
    ), calendars AS (
        SELECT d.pool_id,jsonb_object_agg(to_char(d.day,'YYYY-MM-DD'),eppm.capacity_round3(t.assigned+d.change)) AS days
        FROM deltas d JOIN totals t ON t.pool_id=d.pool_id GROUP BY d.pool_id
    )
    SELECT p.id,coalesce(t.assigned,0.0),t.pool_id IS NOT NULL,
           coalesce(calendar.days,'{}'::jsonb),coalesce(t.people,'[]'::jsonb)
    FROM eppm.resource_pool p LEFT JOIN totals t ON t.pool_id=p.id
    LEFT JOIN calendars calendar ON calendar.pool_id=p.id WHERE p.id=ANY(requested_pools) ORDER BY p.id;
END $$;
REVOKE ALL ON FUNCTION eppm.pool_staffing(bigint[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.pool_staffing(bigint[]) TO eppm_runtime;
