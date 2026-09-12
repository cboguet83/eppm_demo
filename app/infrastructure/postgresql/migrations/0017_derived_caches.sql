-- Private, replaceable payloads. A session/entity has at most one stored entry.
CREATE TABLE eppm.pool_capacity_cache (
    user_id bigint NOT NULL REFERENCES eppm.app_user(id) ON DELETE CASCADE,
    session_hash text NOT NULL REFERENCES eppm.app_session(session_hash) ON DELETE CASCADE,
    pool_id bigint NOT NULL REFERENCES eppm.resource_pool(id) ON DELETE CASCADE,
    source_token text NOT NULL CHECK(source_token ~ '^[a-f0-9]{64}$'),
    day date NOT NULL, format_version integer NOT NULL CHECK(format_version>0),
    summary jsonb NOT NULL CHECK(jsonb_typeof(summary)='object'),
    detail jsonb NOT NULL CHECK(jsonb_typeof(detail)='object'),
    PRIMARY KEY(user_id,session_hash,pool_id)
);
CREATE TABLE eppm.planning_summary_cache (
    user_id bigint NOT NULL REFERENCES eppm.app_user(id) ON DELETE CASCADE,
    session_hash text NOT NULL REFERENCES eppm.app_session(session_hash) ON DELETE CASCADE,
    project_id bigint NOT NULL REFERENCES eppm.project(id) ON DELETE CASCADE,
    source_token text NOT NULL CHECK(source_token ~ '^[a-f0-9]{64}$'),
    day date NOT NULL, format_version integer NOT NULL CHECK(format_version>0),
    summary jsonb NOT NULL CHECK(jsonb_typeof(summary)='object'),
    detail jsonb NOT NULL CHECK(jsonb_typeof(detail)='object'),
    PRIMARY KEY(user_id,session_hash,project_id)
);
REVOKE ALL ON eppm.pool_capacity_cache,eppm.planning_summary_cache FROM PUBLIC,eppm_runtime;

-- These JSON arrays match RevisionSnapshot's stable JSON fingerprints. Filter
-- selected entities before expanding dependency versions or hashing their keys.
CREATE FUNCTION eppm.current_cache_keys(kind text, selected_ids bigint[])
RETURNS TABLE(entity_id bigint, source_token text, entity_name text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE metadata jsonb; actor jsonb; access_token text;
BEGIN
    IF kind IS NULL OR kind NOT IN ('capacity','planning') THEN
        RAISE EXCEPTION 'Unknown cache kind' USING ERRCODE='22023';
    END IF;
    metadata := eppm.display_cache_revisions();
    actor := eppm.current_actor();
    SELECT encode(eppm_crypto.digest(convert_to(jsonb_build_array(
        jsonb_build_array(metadata->'epoch',metadata->'database_oid',actor->'user_id',actor->'session_hash'),
        metadata->'catalog',metadata->'security',
        coalesce(jsonb_agg(project.value->0 ORDER BY project.ordinality),'[]'::jsonb)
    )::text,'UTF8'),'sha256'),'hex') INTO access_token
    FROM jsonb_array_elements(metadata->'projects') WITH ORDINALITY project(value,ordinality);
    RETURN QUERY
    WITH projects AS MATERIALIZED (
        SELECT (value->>0)::bigint AS id,jsonb_build_array(value->0,value->1,value->2) AS version,value->3 AS sources
        FROM jsonb_array_elements(metadata->'projects')
    ), entities AS MATERIALIZED (
        SELECT (value->>0)::bigint AS id,jsonb_build_array(value->0,value->1,value->2) AS version,
               value->>3 AS name,value->4 AS sources FROM jsonb_array_elements(metadata->'pools')
        WHERE kind='capacity' AND (selected_ids IS NULL OR (value->>0)::bigint=ANY(selected_ids))
        UNION ALL SELECT p.id,p.version,project.name,p.sources FROM projects p JOIN eppm.project project ON project.id=p.id
        WHERE kind='planning' AND (selected_ids IS NULL OR p.id=ANY(selected_ids))
    ), source_versions AS (
        SELECT entity.id,jsonb_agg(project.version ORDER BY project.id) AS versions
        FROM entities entity CROSS JOIN LATERAL jsonb_array_elements_text(entity.sources) source(id)
        JOIN projects project ON project.id=source.id::bigint GROUP BY entity.id
    )
    SELECT entity.id,encode(eppm_crypto.digest(convert_to(
        jsonb_build_array(access_token,entity.version,coalesce(sources.versions,'[]'::jsonb))::text,'UTF8'),'sha256'),'hex'),entity.name
    FROM entities entity LEFT JOIN source_versions sources ON sources.id=entity.id;
END $$;
REVOKE ALL ON FUNCTION eppm.current_cache_keys(text,bigint[]) FROM PUBLIC,eppm_runtime;

-- Callers select entities, never stale source keys. Known memory keys can omit
-- payload transfer only when they match keys generated in this read snapshot.
CREATE FUNCTION eppm.read_derived_cache(kind text, selected_ids bigint[], requested_day date, version integer,
                                       details boolean, known_tokens text[])
RETURNS TABLE(entity_id bigint, source_token text, payload jsonb, available boolean, show_staff boolean)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE actor jsonb; shared boolean;
BEGIN
    actor := eppm.current_actor();
    shared := eppm.has_global_permission('business.manage');
    RETURN QUERY
    WITH keys AS MATERIALIZED (SELECT * FROM eppm.current_cache_keys(kind,selected_ids)),
    results AS (
        SELECT k.entity_id,k.source_token,k.entity_name,
               CASE WHEN k.source_token=ANY(known_tokens) THEN NULL::jsonb
                    WHEN NOT details THEN c.summary WHEN shared THEN c.detail
                    ELSE jsonb_set(c.detail,'{contributing_resources}','[]'::jsonb) END AS data,
               coalesce(k.source_token=ANY(known_tokens),false) OR c.pool_id IS NOT NULL AS found
        FROM keys k LEFT JOIN eppm.pool_capacity_cache c ON c.pool_id=k.entity_id
            AND c.user_id=(actor->>'user_id')::bigint AND c.session_hash=actor->>'session_hash'
            AND c.source_token=k.source_token AND c.day=requested_day AND c.format_version=version
        WHERE kind='capacity'
        UNION ALL
        SELECT k.entity_id,k.source_token,k.entity_name,
               CASE WHEN k.source_token=ANY(known_tokens) THEN NULL::jsonb ELSE c.summary END,
               coalesce(k.source_token=ANY(known_tokens),false) OR c.project_id IS NOT NULL
        FROM keys k LEFT JOIN eppm.planning_summary_cache c ON c.project_id=k.entity_id
            AND c.user_id=(actor->>'user_id')::bigint AND c.session_hash=actor->>'session_hash'
            AND c.source_token=k.source_token AND c.day=requested_day AND c.format_version=version
        WHERE kind='planning'
    ) SELECT r.entity_id,r.source_token,r.data,r.found,shared FROM results r
      ORDER BY CASE WHEN kind='planning' THEN r.entity_id END,r.entity_name COLLATE "C",r.entity_id;
END $$;
REVOKE ALL ON FUNCTION eppm.read_derived_cache(text,bigint[],date,integer,boolean,text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.read_derived_cache(text,bigint[],date,integer,boolean,text[]) TO eppm_runtime;

-- Only the server may attest calculated payloads. Hash the external body in the
-- small signed envelope so large details do not exceed the proof document bound.
CREATE FUNCTION eppm.publish_derived_cache(document text, signature text, body text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE request jsonb; data jsonb; actor jsonb; wanted jsonb; kind text; requested_day date; version integer;
        selected_ids bigint[]; total integer; valid integer; shared boolean; visible bigint[];
BEGIN
    request := eppm.verified_server_request(document,signature,'cache.publish');
    IF body IS NULL OR request->>'body_hash' IS DISTINCT FROM
        encode(eppm_crypto.digest(convert_to(body,'UTF8'),'sha256'),'hex') THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    IF current_setting('transaction_isolation')<>'serializable' OR current_setting('transaction_read_only')='on' THEN
        RAISE EXCEPTION 'Cache publication requires a serializable transaction' USING ERRCODE='25001';
    END IF;
    actor := eppm.current_actor();
    IF NOT eppm.has_business_read() THEN RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501'; END IF;
    data := body::jsonb; kind := data->>'kind'; requested_day := (data->>'day')::date; version := (data->>'version')::integer;
    wanted := data->'entries';
    IF kind IS NULL OR kind NOT IN ('capacity','planning') OR requested_day IS NULL OR version IS NULL OR version<1
       OR jsonb_typeof(wanted) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Invalid cache payload' USING ERRCODE='22023';
    END IF;
    SELECT count(*),count(DISTINCT entry.entity_id),array_agg(entry.entity_id ORDER BY entry.entity_id)
        INTO total,valid,selected_ids
        FROM jsonb_to_recordset(wanted) entry(entity_id bigint,token text,summary jsonb,detail jsonb)
        WHERE entry.entity_id>0 AND entry.token ~ '^[a-f0-9]{64}$'
          AND jsonb_typeof(entry.summary)='object' AND jsonb_typeof(entry.detail)='object'
          AND (entry.summary->>CASE WHEN kind='capacity' THEN 'pool_id' ELSE 'id' END)::bigint=entry.entity_id
          AND (entry.detail->>CASE WHEN kind='capacity' THEN 'pool_id' ELSE 'id' END)::bigint=entry.entity_id;
    IF total<>jsonb_array_length(wanted) OR total<>valid THEN
        RAISE EXCEPTION 'Invalid cache payload' USING ERRCODE='22023';
    END IF;
    SELECT count(*) INTO valid FROM jsonb_to_recordset(wanted) entry(entity_id bigint,token text)
        JOIN eppm.current_cache_keys(kind,selected_ids) current_key
          ON current_key.entity_id=entry.entity_id AND current_key.source_token=entry.token;
    IF valid<>total THEN RETURN false; END IF;
    shared := eppm.has_global_permission('business.manage');
    visible := eppm.permission_projects('project.read');
    IF kind='capacity' THEN
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(wanted) entry
                  CROSS JOIN LATERAL jsonb_array_elements(entry->'detail'->'assignments') assignment
                  WHERE (assignment->>'project_id')::bigint IS NULL
                     OR NOT (assignment->>'project_id')::bigint=ANY(visible)) THEN
            RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
        END IF;
        INSERT INTO eppm.pool_capacity_cache(user_id,session_hash,pool_id,source_token,day,format_version,summary,detail)
            SELECT (actor->>'user_id')::bigint,actor->>'session_hash',entry.entity_id,entry.token,requested_day,version,entry.summary,
                   CASE WHEN shared THEN entry.detail ELSE jsonb_set(entry.detail,'{contributing_resources}','[]'::jsonb) END
            FROM jsonb_to_recordset(wanted) entry(entity_id bigint,token text,summary jsonb,detail jsonb)
        ON CONFLICT(user_id,session_hash,pool_id) DO UPDATE SET source_token=excluded.source_token,day=excluded.day,
            format_version=excluded.format_version,summary=excluded.summary,detail=excluded.detail;
    ELSE
        INSERT INTO eppm.planning_summary_cache(user_id,session_hash,project_id,source_token,day,format_version,summary,detail)
            SELECT (actor->>'user_id')::bigint,actor->>'session_hash',entry.entity_id,entry.token,requested_day,version,entry.summary,entry.detail
            FROM jsonb_to_recordset(wanted) entry(entity_id bigint,token text,summary jsonb,detail jsonb)
        ON CONFLICT(user_id,session_hash,project_id) DO UPDATE SET source_token=excluded.source_token,day=excluded.day,
            format_version=excluded.format_version,summary=excluded.summary,detail=excluded.detail;
    END IF;
    RETURN true;
END $$;
REVOKE ALL ON FUNCTION eppm.publish_derived_cache(text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.publish_derived_cache(text,text,text) TO eppm_runtime;
