-- Fresh PostgreSQL lifecycle metadata. Operator provisioning creates eppm_runtime.
-- No business imports, application identities, or access grants are seeded here.
CREATE TABLE eppm.database_identity (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    epoch uuid NOT NULL DEFAULT gen_random_uuid()
);
INSERT INTO eppm.database_identity DEFAULT VALUES;
REVOKE ALL ON ALL TABLES IN SCHEMA eppm FROM PUBLIC;
GRANT USAGE ON SCHEMA eppm TO eppm_runtime;
GRANT SELECT ON eppm.database_identity, eppm.schema_migration TO eppm_runtime;
