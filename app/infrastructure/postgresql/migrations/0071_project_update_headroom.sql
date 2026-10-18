-- Keep independent title updates on their existing heap pages where possible.
-- No business rule, row policy, authorization or transaction replay change.
ALTER TABLE eppm.project SET (fillfactor = 70);

-- Apply the reserved page space to populated installations as well as new ones.
-- Run through operator migrations during a maintenance window: CLUSTER holds
-- an exclusive table lock and needs temporary table/index rebuild disk space.
CLUSTER eppm.project USING project_pkey;
ANALYZE eppm.project;
