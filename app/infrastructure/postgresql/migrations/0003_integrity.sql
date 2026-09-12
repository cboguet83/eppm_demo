-- Permanent invariants run independently of Python and apply to direct writes.
-- Definer helpers see complete constraint inputs; they expose no row contents.
SET LOCAL search_path = pg_catalog, eppm;

ALTER TABLE eppm.project ADD CONSTRAINT project_planned_finite
    CHECK (planned_budget > '-Infinity'::numeric AND planned_budget < 'Infinity'::numeric);
ALTER TABLE eppm.project ADD CONSTRAINT project_actual_finite
    CHECK (actual_budget > '-Infinity'::numeric AND actual_budget < 'Infinity'::numeric);
ALTER TABLE eppm.project_task ADD CONSTRAINT task_date_order CHECK (start_date <= end_date);
ALTER TABLE eppm.project_task ADD CONSTRAINT task_progress_range CHECK (progress_pct BETWEEN 0 AND 100);

CREATE FUNCTION eppm.require_serializable_write() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, eppm AS $$
BEGIN
    IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = session_user)
       AND pg_has_role(session_user, 'eppm_runtime', 'MEMBER')
       AND current_setting('transaction_isolation') <> 'serializable' THEN
        RAISE EXCEPTION 'Business mutations require a serializable transaction' USING ERRCODE = '25001';
    END IF;
    RETURN NULL;
END $$;

DO $$
DECLARE target text;
BEGIN
    FOR target IN SELECT tablename FROM pg_tables WHERE schemaname = 'eppm'
        AND tablename NOT IN ('schema_migration', 'database_identity', 'app_oidc_state', 'app_session')
    LOOP
        EXECUTE format('CREATE TRIGGER require_serializable BEFORE INSERT OR UPDATE OR DELETE ON eppm.%I
                        FOR EACH STATEMENT EXECUTE FUNCTION eppm.require_serializable_write()', target);
    END LOOP;
END $$;

CREATE FUNCTION eppm.reject_immutable_change() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, eppm AS $$
BEGIN
    RAISE EXCEPTION 'Historical records are immutable' USING ERRCODE = '23514';
END $$;
DO $$
DECLARE target text;
BEGIN
    FOREACH target IN ARRAY ARRAY['app_security_audit', 'finance_row', 'finance_amount', 'finance_cancellation']
    LOOP
        EXECUTE format('CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON eppm.%I
                        FOR EACH ROW EXECUTE FUNCTION eppm.reject_immutable_change()', target);
        EXECUTE format('CREATE TRIGGER immutable_history BEFORE TRUNCATE ON eppm.%I
                        FOR EACH STATEMENT EXECUTE FUNCTION eppm.reject_immutable_change()', target);
    END LOOP;
END $$;
CREATE TRIGGER finance_no_truncate BEFORE TRUNCATE ON eppm.finance_snapshot
    FOR EACH STATEMENT EXECUTE FUNCTION eppm.reject_immutable_change();

CREATE FUNCTION eppm.guard_finance_snapshot() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, eppm AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.sealed THEN
        RAISE EXCEPTION 'Budget snapshots are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER finance_snapshot_immutable BEFORE UPDATE OR DELETE ON eppm.finance_snapshot
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_finance_snapshot();

CREATE FUNCTION eppm.guard_finance_child() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
DECLARE parent_sealed boolean;
BEGIN
    SELECT sealed INTO parent_sealed FROM eppm.finance_snapshot WHERE id = NEW.snapshot_id FOR UPDATE;
    IF parent_sealed THEN
        RAISE EXCEPTION 'Budget snapshots are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER finance_row_sealed BEFORE INSERT ON eppm.finance_row
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_finance_child();
CREATE TRIGGER finance_amount_sealed BEFORE INSERT ON eppm.finance_amount
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_finance_child();

CREATE FUNCTION eppm.guard_finance_cancellation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
DECLARE parent eppm.finance_snapshot;
BEGIN
    SELECT * INTO parent FROM eppm.finance_snapshot WHERE id = NEW.snapshot_id FOR UPDATE;
    IF parent.id IS NULL OR NOT parent.sealed OR parent.status = 'Canceled' OR parent.status <> NEW.previous_status THEN
        RAISE EXCEPTION 'Invalid budget cancellation' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER finance_cancellation_valid BEFORE INSERT ON eppm.finance_cancellation
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_finance_cancellation();

CREATE FUNCTION eppm.guard_hierarchy_code() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, eppm AS $$
BEGIN
    IF NEW.code IS DISTINCT FROM OLD.code THEN
        RAISE EXCEPTION 'Hierarchy type codes are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER hierarchy_type_stable_code BEFORE UPDATE OF code ON eppm.hierarchy_type
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_hierarchy_code();

CREATE FUNCTION eppm.guard_pool_group_cycle() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
BEGIN
    -- One hierarchy mutation lock, not a lock on other business writes.
    PERFORM pg_advisory_xact_lock(hashtextextended('eppm:pool-group-hierarchy', 0));
    IF NEW.child_group_id IS NOT NULL AND EXISTS (
        WITH RECURSIVE descendants(id) AS (
            SELECT NEW.child_group_id
            UNION
            SELECT gm.child_group_id FROM eppm.resource_pool_group_member gm
            JOIN descendants d ON gm.group_id = d.id
            WHERE gm.child_group_id IS NOT NULL AND gm.id IS DISTINCT FROM NEW.id
        )
        SELECT 1 FROM descendants WHERE id = NEW.group_id
    ) THEN
        RAISE EXCEPTION 'Pool group membership would create a cycle' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER pool_group_no_cycle BEFORE INSERT OR UPDATE OF group_id, child_group_id
    ON eppm.resource_pool_group_member FOR EACH ROW EXECUTE FUNCTION eppm.guard_pool_group_cycle();

CREATE FUNCTION eppm.guard_calendar_overlap() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
DECLARE employee_key bigint;
BEGIN
    FOR employee_key IN SELECT DISTINCT value FROM unnest(ARRAY[NEW.employee_id, OLD.employee_id]) value
        WHERE value IS NOT NULL ORDER BY value
    LOOP
        PERFORM pg_advisory_xact_lock(hashtextextended('eppm:calendar:' || employee_key, 0));
    END LOOP;
    IF EXISTS (
        SELECT 1 FROM eppm.employee_calendar_exception exception
        WHERE exception.employee_id = NEW.employee_id
          AND exception.exception_id IS DISTINCT FROM NEW.exception_id
          AND exception.start_date <= NEW.end_date AND exception.end_date >= NEW.start_date
    ) THEN
        RAISE EXCEPTION 'Employee calendar exceptions must not overlap' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER calendar_no_overlap BEFORE INSERT OR UPDATE ON eppm.employee_calendar_exception
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_calendar_overlap();

CREATE FUNCTION eppm.guard_wbs_total() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
DECLARE wbs_key bigint;
BEGIN
    FOR wbs_key IN SELECT DISTINCT value FROM unnest(ARRAY[NEW.wbs_id, OLD.wbs_id]) value
        WHERE value IS NOT NULL ORDER BY value
    LOOP
        PERFORM pg_advisory_xact_lock(hashtextextended('eppm:wbs:' || wbs_key, 0));
    END LOOP;
    IF NEW.percentage + (SELECT coalesce(sum(percentage), 0) FROM eppm.project_wbs
        WHERE wbs_id = NEW.wbs_id AND (TG_OP <> 'UPDATE' OR (project_id, wbs_id) <> (OLD.project_id, OLD.wbs_id))) > 100 THEN
        RAISE EXCEPTION 'WBS total allocation cannot exceed 100%%' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER project_wbs_total BEFORE INSERT OR UPDATE ON eppm.project_wbs
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_wbs_total();

CREATE FUNCTION eppm.guard_assignment_owner() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
BEGIN
    IF NEW.task_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM eppm.project_task WHERE id = NEW.task_id AND project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION 'Invalid resource assignment reference' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER pool_assignment_owner BEFORE INSERT OR UPDATE ON eppm.resource_pool_assignment
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_assignment_owner();

CREATE FUNCTION eppm.guard_task_assignment_owner() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
BEGIN
    IF OLD.project_id IS DISTINCT FROM NEW.project_id AND EXISTS (
        SELECT 1 FROM eppm.resource_pool_assignment WHERE task_id = NEW.id AND project_id <> NEW.project_id
    ) THEN
        RAISE EXCEPTION 'Invalid resource assignment reference' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER task_assignment_owner BEFORE UPDATE OF project_id ON eppm.project_task
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_task_assignment_owner();

CREATE FUNCTION eppm.classify_blocking_event() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
BEGIN
    IF NEW.name = 'Blocking Point' AND NEW.system_code IS NULL
       AND NOT EXISTS (SELECT 1 FROM eppm.project_event_type WHERE system_code = 'blocking_point') THEN
        NEW.system_code := 'blocking_point';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER project_event_type_classify BEFORE INSERT ON eppm.project_event_type
    FOR EACH ROW EXECUTE FUNCTION eppm.classify_blocking_event();

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA eppm FROM PUBLIC;
