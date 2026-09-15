-- Optional team ancestry; existing teams remain roots.
ALTER TABLE eppm.team ADD COLUMN parent_team_id bigint
    REFERENCES eppm.team(team_id) ON DELETE RESTRICT;
ALTER TABLE eppm.team ADD CONSTRAINT team_parent_not_self
    CHECK (parent_team_id IS DISTINCT FROM team_id);
CREATE INDEX team_parent ON eppm.team(parent_team_id);

CREATE FUNCTION eppm.guard_team_parent_cycle() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm AS $$
BEGIN
    IF NEW.parent_team_id IS NULL THEN
        RETURN NEW;
    END IF;
    -- Application writes are SERIALIZABLE; conflicting snapshots are replayed.
    PERFORM pg_advisory_xact_lock(hashtextextended('eppm:team-hierarchy', 0));
    IF EXISTS (
        WITH RECURSIVE ancestors(id) AS (
            SELECT NEW.parent_team_id
            UNION
            SELECT t.parent_team_id FROM eppm.team t
            JOIN ancestors a ON t.team_id = a.id
            WHERE t.parent_team_id IS NOT NULL
        )
        SELECT 1 FROM ancestors WHERE id = NEW.team_id
    ) THEN
        RAISE EXCEPTION 'Team parent link would create a cycle' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION eppm.guard_team_parent_cycle() FROM PUBLIC;
CREATE TRIGGER team_parent_no_cycle BEFORE INSERT OR UPDATE OF parent_team_id
    ON eppm.team FOR EACH ROW EXECUTE FUNCTION eppm.guard_team_parent_cycle();
