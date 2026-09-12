-- Preserve the existing minimal project-label contract without exposing employee records.
CREATE VIEW eppm.employee_name_directory WITH (security_barrier = true) AS
    SELECT function_id, firstname, lastname FROM eppm.employee
    WHERE (SELECT eppm.has_business_read());
GRANT SELECT ON eppm.employee_name_directory TO eppm_runtime;
