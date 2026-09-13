-- ANALYZE can make sequential scans attractive for these small security tables.
-- Under SERIALIZABLE, a session lookup then takes a relation-wide predicate lock
-- and independent activity updates can conflict. Favor the existing indexes for
-- these exact session/user lookups and updates. Function-local settings restore
-- the caller's planner policy; proofs, row locks, isolation and retries remain.
ALTER FUNCTION eppm.bind_actor(text,text) SET enable_seqscan = off;
ALTER FUNCTION eppm.current_actor(boolean) SET enable_seqscan = off;
ALTER FUNCTION eppm.session_activity() SET enable_seqscan = off;
