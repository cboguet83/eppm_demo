-- Effective portfolio scopes range from a few IDs to the complete portfolio.
-- Reusing a generic plan for the visible-ID arrays turns warm full-scope reads
-- into hundreds of thousands of repeated index probes. Plan this function for
-- its current scope; PostgreSQL restores the caller's setting on return.
-- Its body, signed actor checks, visible sources and cache keys are unchanged.
ALTER FUNCTION eppm.display_cache_revisions() SET plan_cache_mode = force_custom_plan;
