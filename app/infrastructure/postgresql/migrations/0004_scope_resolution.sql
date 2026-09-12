-- Private scope resolution and stable categorical reference lifetimes.
-- These helpers are not exposed to runtime callers; subsequent policies invoke
-- them only for the authenticated actor's persisted grants.
SET LOCAL search_path = pg_catalog, eppm;

CREATE FUNCTION eppm.scope_reference_ids(document jsonb) RETURNS bigint[]
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog, eppm AS $$
DECLARE value jsonb; result bigint[] := ARRAY[]::bigint[];
BEGIN
    IF jsonb_typeof(document) IS DISTINCT FROM 'array' THEN RETURN NULL; END IF;
    IF jsonb_array_length(document) NOT BETWEEN 1 AND 10000 THEN RETURN NULL; END IF;
    FOR value IN SELECT jsonb_array_elements(document)
    LOOP
        IF jsonb_typeof(value) <> 'number' OR value::text !~ '^[1-9][0-9]*$' THEN RETURN NULL; END IF;
        IF value::numeric > 9223372036854775807 THEN RETURN NULL; END IF;
        result := array_append(result, value::text::bigint);
    END LOOP;
    RETURN ARRAY(SELECT DISTINCT item FROM unnest(result) item ORDER BY item);
END $$;

CREATE FUNCTION eppm.valid_scope_structure(document jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog, eppm AS $$
DECLARE kind text; projects jsonb; conditions jsonb; condition jsonb; ids bigint[];
BEGIN
    IF jsonb_typeof(document) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(document) key WHERE key NOT IN ('kind','project_ids','conditions')) THEN RETURN false; END IF;
    kind := document ->> 'kind';
    projects := coalesce(document -> 'project_ids', '[]'::jsonb);
    conditions := coalesce(document -> 'conditions', '[]'::jsonb);
    IF kind = 'all' THEN RETURN projects = '[]'::jsonb AND conditions = '[]'::jsonb; END IF;
    IF kind = 'projects' THEN RETURN eppm.scope_reference_ids(projects) IS NOT NULL AND conditions = '[]'::jsonb; END IF;
    IF kind IS DISTINCT FROM 'properties' OR projects <> '[]'::jsonb OR jsonb_typeof(conditions) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
    IF jsonb_array_length(conditions) NOT BETWEEN 1 AND 20 THEN RETURN false; END IF;
    FOR condition IN SELECT jsonb_array_elements(conditions)
    LOOP
        IF jsonb_typeof(condition) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
        IF ARRAY(SELECT jsonb_object_keys(condition) ORDER BY 1) <> ARRAY['operator','property_id','value_ids'] THEN RETURN false; END IF;
        IF jsonb_typeof(condition -> 'property_id') IS DISTINCT FROM 'string'
           OR length(condition ->> 'property_id') NOT BETWEEN 1 AND 128 THEN RETURN false; END IF;
        ids := eppm.scope_reference_ids(condition -> 'value_ids');
        IF ids IS NULL OR (condition ->> 'operator') NOT IN ('eq','in') THEN RETURN false; END IF;
        IF (condition ->> 'operator') IS NULL OR (condition ->> 'operator') = 'eq' AND cardinality(ids) <> 1 THEN RETURN false; END IF;
    END LOOP;
    RETURN true;
END $$;

CREATE FUNCTION eppm.resolve_scope(document jsonb) RETURNS bigint[]
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
DECLARE
    kind text; ids bigint[]; matches bigint[]; selected bigint[]; condition jsonb;
    property_key text; parameter_code text; reference_count integer;
BEGIN
    IF NOT eppm.valid_scope_structure(document) THEN
        RAISE EXCEPTION 'Invalid access scope' USING ERRCODE = '22023';
    END IF;
    kind := document ->> 'kind';
    IF kind = 'all' THEN RETURN ARRAY(SELECT id FROM eppm.project ORDER BY id); END IF;
    IF kind = 'projects' THEN
        ids := eppm.scope_reference_ids(document -> 'project_ids');
        IF (SELECT count(*) FROM eppm.project WHERE id = ANY(ids)) <> cardinality(ids) THEN
            RAISE EXCEPTION 'Scope contains a missing project reference' USING ERRCODE = '22023';
        END IF;
        RETURN ids;
    END IF;
    FOR condition IN SELECT jsonb_array_elements(document -> 'conditions')
    LOOP
        ids := eppm.scope_reference_ids(condition -> 'value_ids');
        property_key := condition ->> 'property_id';
        IF property_key = 'project_type_id' THEN
            SELECT count(*) INTO reference_count FROM eppm.project_type WHERE id = ANY(ids);
            selected := ARRAY(SELECT id FROM eppm.project WHERE project_type_id = ANY(ids));
        ELSE
            IF property_key !~ '^enum:[0-9]+$' THEN
                RAISE EXCEPTION 'Property is not in the scope allowlist' USING ERRCODE = '22023';
            END IF;
            IF substr(property_key,6)::numeric NOT BETWEEN 1 AND 9223372036854775807 THEN
                RAISE EXCEPTION 'Property is not in the scope allowlist' USING ERRCODE = '22023';
            END IF;
            SELECT parameter.param_id INTO parameter_code
                FROM eppm.app_scope_property scope_property
                JOIN eppm.schema_parameters parameter ON parameter.param_id = scope_property.param_id
                WHERE scope_property.id = substr(property_key,6)::bigint AND parameter.param_type = 'ENUM';
            IF parameter_code IS NULL THEN
                RAISE EXCEPTION 'Scope contains a missing or unsupported property' USING ERRCODE = '22023';
            END IF;
            SELECT count(*) INTO reference_count FROM eppm.schema_param_options
                WHERE param_id = parameter_code AND id = ANY(ids);
            selected := ARRAY(
                SELECT DISTINCT value.project_id FROM eppm.project_property_value value
                JOIN eppm.schema_param_options option ON option.param_id = value.param_id AND option.option_value = value.text_value
                WHERE value.kind = 'text' AND value.param_id = parameter_code AND option.id = ANY(ids)
            );
        END IF;
        IF reference_count <> cardinality(ids) THEN
            RAISE EXCEPTION 'Scope contains a missing categorical value' USING ERRCODE = '22023';
        END IF;
        matches := CASE WHEN matches IS NULL THEN selected
            ELSE ARRAY(SELECT item FROM unnest(matches) item WHERE item = ANY(selected)) END;
    END LOOP;
    RETURN ARRAY(SELECT DISTINCT item FROM unnest(matches) item ORDER BY item);
END $$;

CREATE FUNCTION eppm.register_scope_property() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
BEGIN
    IF NEW.param_type = 'ENUM' THEN
        INSERT INTO eppm.app_scope_property(param_id) VALUES (NEW.param_id) ON CONFLICT (param_id) DO NOTHING;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER register_scope_property AFTER INSERT OR UPDATE OF param_type ON eppm.schema_parameters
    FOR EACH ROW EXECUTE FUNCTION eppm.register_scope_property();

CREATE FUNCTION eppm.tombstone_scope_property() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.param_type = 'ENUM' AND NEW.param_type <> 'ENUM' THEN
        UPDATE eppm.app_scope_property SET param_id = NULL WHERE param_id = OLD.param_id;
    END IF;
    RETURN coalesce(NEW, OLD);
END $$;
CREATE TRIGGER tombstone_scope_property BEFORE DELETE OR UPDATE OF param_type ON eppm.schema_parameters
    FOR EACH ROW EXECUTE FUNCTION eppm.tombstone_scope_property();

CREATE FUNCTION eppm.invalidate_scope_reference() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
DECLARE property_key text; explanation text;
BEGIN
    IF TG_TABLE_NAME = 'project' THEN
        UPDATE eppm.app_role_assignment SET invalid_reason = 'A selected project was deleted. Revoke and recreate this assignment.'
        WHERE scope_json ->> 'kind' = 'projects' AND scope_json -> 'project_ids' @> to_jsonb(ARRAY[OLD.id]);
        RETURN OLD;
    END IF;
    IF TG_TABLE_NAME = 'project_type' THEN
        property_key := 'project_type_id';
        explanation := 'A selected project type was deleted. Revoke and recreate this assignment.';
    ELSE
        IF TG_OP = 'UPDATE' AND OLD.param_id IS NOT DISTINCT FROM NEW.param_id
           AND OLD.option_value IS NOT DISTINCT FROM NEW.option_value THEN RETURN NEW; END IF;
        SELECT 'enum:' || id INTO property_key FROM eppm.app_scope_property WHERE param_id = OLD.param_id;
        explanation := CASE WHEN TG_OP = 'DELETE'
            THEN 'A selected categorical value was deleted. Revoke and recreate this assignment.'
            ELSE 'A selected categorical value was replaced. Revoke and recreate this assignment.' END;
    END IF;
    UPDATE eppm.app_role_assignment SET invalid_reason = explanation
    WHERE jsonb_typeof(scope_json -> 'conditions') = 'array' AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(scope_json -> 'conditions') = 'array' THEN scope_json -> 'conditions' ELSE '[]'::jsonb END
        ) condition WHERE condition ->> 'property_id' = property_key AND condition -> 'value_ids' @> to_jsonb(ARRAY[OLD.id])
    );
    RETURN coalesce(NEW, OLD);
END $$;
CREATE TRIGGER invalidate_deleted_project BEFORE DELETE ON eppm.project
    FOR EACH ROW EXECUTE FUNCTION eppm.invalidate_scope_reference();
CREATE TRIGGER invalidate_deleted_type BEFORE DELETE ON eppm.project_type
    FOR EACH ROW EXECUTE FUNCTION eppm.invalidate_scope_reference();
CREATE TRIGGER invalidate_changed_option BEFORE DELETE OR UPDATE OF param_id, option_value ON eppm.schema_param_options
    FOR EACH ROW EXECUTE FUNCTION eppm.invalidate_scope_reference();

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA eppm FROM PUBLIC;
