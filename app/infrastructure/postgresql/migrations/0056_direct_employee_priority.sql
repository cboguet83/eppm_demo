-- Staffing changes can affect pools whose own mapping rows were untouched.
CREATE TRIGGER cache_revision AFTER INSERT OR UPDATE OR DELETE ON eppm.pool_staffing_projection
    FOR EACH ROW EXECUTE FUNCTION eppm.invalidate_business_caches('pool');
UPDATE eppm.catalog_cache_revision SET revision=revision+1;
