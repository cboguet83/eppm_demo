-- Resolve narrow pool/date/demand rows before attaching large staffing calendars.
-- This is an execution-plan boundary in the existing private aggregate reader;
-- authorization, demand semantics and Python capacity calculations are unchanged.
DO $$
DECLARE definition text;
BEGIN
    SELECT pg_get_functiondef('eppm.dashboard_resource_breakdown_with_capacity(jsonb,bigint[],date,text,bigint,text,text[],bigint[])'::regprocedure)
        INTO definition;
    IF position('), days AS (' IN definition)=0 THEN
        RAISE EXCEPTION 'Dashboard date join boundary was not found';
    END IF;
    EXECUTE replace(definition, '), days AS (', '), days AS MATERIALIZED (');
END $$;
