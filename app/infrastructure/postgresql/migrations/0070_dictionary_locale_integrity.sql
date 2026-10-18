-- Retain historical locale keys while rejecting new blank locale references.
ALTER TABLE eppm.business_dictionary_translation
    ADD CONSTRAINT dictionary_locale_nonblank
    CHECK (length(trim(locale)) > 0) NOT VALID;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM eppm.business_dictionary_translation
        WHERE length(trim(locale)) = 0) THEN
        ALTER TABLE eppm.business_dictionary_translation
            VALIDATE CONSTRAINT dictionary_locale_nonblank;
    END IF;
END $$;
