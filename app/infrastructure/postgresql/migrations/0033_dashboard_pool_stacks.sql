CREATE FUNCTION eppm.dashboard_resource_breakdown(requested bigint[], effective_day date, selected_quarter text DEFAULT NULL, selected_pool bigint DEFAULT NULL, selected_metric text DEFAULT 'overallocation')
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE visible bigint[]; selected_pools bigint[]; report_year integer; first_day date; last_day date; result jsonb;
BEGIN
    PERFORM eppm.current_actor();
    visible := eppm.permission_projects('project.read');
    IF requested IS NULL OR EXISTS(SELECT 1 FROM unnest(requested) id WHERE id IS NULL OR NOT id=ANY(visible)) THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    IF effective_day IS NULL THEN RAISE EXCEPTION 'A reporting day is required' USING ERRCODE='22023'; END IF;
    report_year := extract(year FROM effective_day)::integer;
    first_day := make_date(report_year-5,1,1); last_day := make_date(report_year+14,12,31);
    IF selected_quarter IS NOT NULL AND NOT EXISTS(
        SELECT 1 FROM generate_series(report_year-5,report_year+14) y CROSS JOIN generate_series(1,4) q
        WHERE selected_quarter=y::text || '-Q' || q::text) THEN
        RAISE EXCEPTION 'Select a quarter in the displayed date range' USING ERRCODE='22023';
    END IF;
    SELECT coalesce(array_agg(DISTINCT pool_id),'{}') INTO selected_pools
        FROM eppm.resource_pool_assignment WHERE project_id=ANY(requested) AND fte_assigned>0;
    IF selected_metric NOT IN ('overallocation','allocation') OR selected_metric IS NULL THEN
        RAISE EXCEPTION 'Invalid resource metric' USING ERRCODE='22023';
    END IF;
    IF selected_pool IS NOT NULL AND NOT selected_pool=ANY(selected_pools) THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    IF cardinality(selected_pools)=0 THEN
        SELECT jsonb_build_object('overallocation',jsonb_object_agg(y::text || '-Q' || q::text,0.0),
                                  'capacity',jsonb_object_agg(y::text || '-Q' || q::text,0.0),
                                  'allocation',jsonb_object_agg(y::text || '-Q' || q::text,0.0),'pools','[]'::jsonb,'consumers','[]'::jsonb)
            INTO result FROM generate_series(report_year-5,report_year+14) y CROSS JOIN generate_series(1,4) q;
        RETURN result;
    END IF;
    WITH staffing AS MATERIALIZED (
        SELECT * FROM eppm.pool_effective_capacity(selected_pools)
    ), assignments AS MATERIALIZED (
        SELECT * FROM eppm.resource_pool_assignment WHERE pool_id=ANY(selected_pools)
    ), bounds AS (
        SELECT project_id,min(start_date) AS first,max(end_date) AS last FROM eppm.project_task
        WHERE project_id IN (SELECT project_id FROM assignments) GROUP BY project_id
    ), resolved AS MATERIALIZED (
        SELECT a.id,a.pool_id,a.project_id,a.task_id,a.fte_assigned,
            coalesce(relative.first,a.start_date,t.start_date,b.first,effective_day) AS first,
            coalesce(relative.last,a.end_date,t.end_date,b.last,effective_day) AS last
        FROM assignments a LEFT JOIN eppm.project_task t ON t.id=a.task_id LEFT JOIN bounds b ON b.project_id=a.project_id
        LEFT JOIN LATERAL eppm.assignment_period(coalesce(t.start_date,b.first,effective_day),
            coalesce(t.end_date,b.last,effective_day),a.schedule_anchor,a.offset_days,a.duration_days) relative ON true
    ), events AS (
        SELECT a.*,a.first AS day,1 AS sign FROM resolved a
        UNION ALL SELECT a.*,least(greatest(a.first,a.last)+1,a.first+9125),-1 FROM resolved a
    ), project_events AS (
        SELECT pool_id,project_id,day,sum(sign) AS coverage,
            coalesce(sum(fte_assigned*sign ORDER BY task_id NULLS FIRST,id) FILTER (WHERE task_id IS NULL),0.0) AS project_change,
            coalesce(sum(fte_assigned*sign ORDER BY task_id NULLS FIRST,id) FILTER (WHERE task_id IS NOT NULL),0.0) AS task_change
        FROM events GROUP BY pool_id,project_id,day
    ), project_values AS (
        SELECT pool_id,project_id,day,coverage,greatest(
            sum(project_change) OVER(PARTITION BY pool_id,project_id ORDER BY day ROWS UNBOUNDED PRECEDING),
            sum(task_change) OVER(PARTITION BY pool_id,project_id ORDER BY day ROWS UNBOUNDED PRECEDING)) AS demand
        FROM project_events
    ), project_deltas AS (
        SELECT pool_id,project_id,day,coverage,
            demand-lag(demand,1,0.0) OVER(PARTITION BY pool_id,project_id ORDER BY day) AS change FROM project_values
    ), pool_events AS (
        SELECT pool_id,day,sum(coverage) AS coverage,sum(change ORDER BY project_id) AS change
        FROM project_deltas GROUP BY pool_id,day
    ), intervals AS (
        SELECT pool_id,day,lead(day) OVER(PARTITION BY pool_id ORDER BY day) AS stop,
            sum(coverage) OVER(PARTITION BY pool_id ORDER BY day ROWS UNBOUNDED PRECEDING) AS active,
            eppm.capacity_round3(sum(change) OVER(PARTITION BY pool_id ORDER BY day ROWS UNBOUNDED PRECEDING)) AS demand
        FROM pool_events
    ), days AS (
        SELECT i.pool_id,greatest(i.day,first_day)+offset_days AS day,i.demand
        FROM intervals i CROSS JOIN LATERAL generate_series(0,
            least(i.stop,last_day+1)-greatest(i.day,first_day)-1) offset_days
        WHERE i.active>0 AND i.day<=last_day AND i.stop>first_day
    ), comparisons AS (
        SELECT d.*,eppm.capacity_round3(coalesce((s.calendar->>to_char(d.day,'YYYY-MM-DD'))::double precision,s.base)) AS capacity
        FROM days d JOIN staffing s ON s.pool_id=d.pool_id
        WHERE EXISTS(SELECT 1 FROM resolved a WHERE a.pool_id=d.pool_id AND a.project_id=ANY(requested)
                     AND a.fte_assigned>0 AND a.first<=d.day AND a.last>=d.day)
    ), shortages AS MATERIALIZED (
        SELECT pool_id,day,eppm.capacity_round3(demand-capacity)::text::numeric AS excess
        FROM comparisons WHERE demand>capacity+0.0001::double precision
    ), daily_shortage AS (
        SELECT day,sum(excess) AS total FROM shortages GROUP BY day
    ), capacity_deltas AS (
        SELECT item.key::date AS day,sum(item.value::numeric-s.base::text::numeric) AS change
        FROM staffing s CROSS JOIN LATERAL jsonb_each_text(s.calendar) item
        WHERE item.key::date BETWEEN first_day AND last_day GROUP BY item.key::date
    ), quarters AS (
        SELECT y::text || '-Q' || q::text AS name,make_date(y,3*q-2,1) AS first,
            (make_date(y,3*q-2,1)+interval '3 months')::date-1 AS last
        FROM generate_series(report_year-5,report_year+14) y CROSS JOIN generate_series(1,4) q
    ), quarter_capacity AS (
        SELECT q.name,coalesce((SELECT sum(s.base::text::numeric) FROM staffing s),0)+
            coalesce(greatest(max(d.change),CASE WHEN count(d.day)<q.last-q.first+1 THEN 0::numeric END),0) AS capacity
        FROM quarters q LEFT JOIN capacity_deltas d ON d.day BETWEEN q.first AND q.last GROUP BY q.name,q.first,q.last
    ), quarter_shortage AS (
        SELECT q.name,coalesce(max(d.total),0) AS shortage
        FROM quarters q LEFT JOIN daily_shortage d ON d.day BETWEEN q.first AND q.last GROUP BY q.name
    ), daily_allocation AS (
        SELECT day,sum(eppm.capacity_round3(demand)::text::numeric) AS total FROM comparisons GROUP BY day
    ), allocation_peaks AS (
        SELECT DISTINCT ON(q.name) q.name,d.day,coalesce(d.total,0) AS total FROM quarters q
        LEFT JOIN daily_allocation d ON d.day BETWEEN q.first AND q.last ORDER BY q.name,d.total DESC NULLS LAST,d.day
    ), shortage_peaks AS (
        SELECT DISTINCT ON(q.name) q.name,d.day,coalesce(d.total,0) AS total FROM quarters q
        LEFT JOIN daily_shortage d ON d.day BETWEEN q.first AND q.last ORDER BY q.name,d.total DESC NULLS LAST,d.day
    ), pool_series AS (
        SELECT p.id AS pool_id,p.name,
            (SELECT jsonb_object_agg(q.name,coalesce(s.excess,0)) FROM shortage_peaks q
                LEFT JOIN shortages s ON s.pool_id=p.id AND s.day=q.day) AS overallocation,
            (SELECT jsonb_object_agg(q.name,coalesce(eppm.capacity_round3(c.demand),0)) FROM allocation_peaks q
                LEFT JOIN comparisons c ON c.pool_id=p.id AND c.day=q.day) AS allocation
        FROM eppm.resource_pool p WHERE p.id=ANY(selected_pools)
    ), responsible AS (
        SELECT DISTINCT s.pool_id FROM comparisons s JOIN quarters q ON s.day BETWEEN q.first AND q.last
        WHERE q.name=selected_quarter AND (selected_pool IS NULL OR s.pool_id=selected_pool)
          AND CASE WHEN selected_metric='allocation' THEN s.demand>0 ELSE s.demand>s.capacity+0.0001 END
    ), consumers AS (
        SELECT DISTINCT a.project_id FROM resolved a JOIN responsible r ON r.pool_id=a.pool_id
        JOIN quarters q ON q.name=selected_quarter
        WHERE a.project_id=ANY(visible) AND a.fte_assigned>0 AND a.first<=q.last AND a.last>=q.first
    ) SELECT jsonb_build_object(
        'overallocation',(SELECT jsonb_object_agg(name,shortage) FROM quarter_shortage),
        'capacity',(SELECT jsonb_object_agg(name,capacity) FROM quarter_capacity),
        'allocation',(SELECT jsonb_object_agg(name,total) FROM allocation_peaks),
        'pools',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY pool_id),'[]'::jsonb) FROM pool_series p),
        'peak_days',jsonb_build_object('allocation',(SELECT jsonb_object_agg(name,day) FROM allocation_peaks),
                                      'overallocation',(SELECT jsonb_object_agg(name,day) FROM shortage_peaks)),
        'consumers',coalesce((SELECT jsonb_agg(project_id ORDER BY project_id) FROM consumers),'[]'::jsonb)
    ) INTO result;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION eppm.dashboard_resource_breakdown(bigint[],date,text,bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.dashboard_resource_breakdown(bigint[],date,text,bigint,text) TO eppm_runtime;

CREATE OR REPLACE FUNCTION eppm.dashboard_resources(requested bigint[], effective_day date, selected_quarter text DEFAULT NULL)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,eppm,pg_temp AS $$
    SELECT eppm.dashboard_resource_breakdown(requested,effective_day,selected_quarter) - 'pools' - 'allocation' - 'peak_days'
$$;
