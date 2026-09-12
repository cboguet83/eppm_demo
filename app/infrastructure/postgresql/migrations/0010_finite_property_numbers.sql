-- Numeric properties share the domain's finite-number invariant, including defaults.
ALTER TABLE eppm.project_property_value ADD CONSTRAINT project_property_number_finite
    CHECK (number_value > '-Infinity'::numeric AND number_value < 'Infinity'::numeric);
ALTER TABLE eppm.project_type_property_default ADD CONSTRAINT project_default_number_finite
    CHECK (number_value > '-Infinity'::numeric AND number_value < 'Infinity'::numeric);
