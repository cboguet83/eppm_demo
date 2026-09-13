-- An integer target rounds numeric SQL input before CHECK constraints run.
-- Retain exact input until the whole-percentage check has rejected fractions.
-- Existing shares are integers, so conversion preserves every stored value.
ALTER TABLE eppm.project_wbs
    ALTER COLUMN percentage TYPE numeric USING percentage::numeric,
    ADD CONSTRAINT project_wbs_whole_percentage CHECK (percentage = trunc(percentage));
