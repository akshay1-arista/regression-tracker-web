# Migration Guide: PR #18 - Path-Based Module Tracking & Priority Filtering

## Overview

PR #18 introduces **two major changes** to the Regression Tracker:

1. **Path-Based Module Tracking**: Modules are now derived from test file paths instead of Jenkins job modules
2. **Priority Filtering**: UI controls to filter Module Statistics by test priority (P0, P1, P2, P3, UNKNOWN)

This guide explains the changes, breaking changes, and migration steps required.

---

## What Changed

### 1. Path-Based Module Categorization

**Before (Jenkins-Based):**
- Modules were determined by which Jenkins job executed the tests
- A test in `data_plane/tests/routing/bgp/` could appear in the `business_policy` module if that job ran it
- This caused cross-contamination: 61.5% of tests appeared in the "wrong" module

**After (Path-Based):**
- Modules are extracted from the test file path: `data_plane/tests/{module_name}/*`
- Tests always appear in their correct module regardless of which Jenkins job ran them
- New database field: `test_results.testcase_module`

**Impact:**
- More accurate module grouping
- Dashboard "All Modules" view shows path-based modules
- Trends page uses path-based filtering

### 2. Priority Filtering

**New Feature:**
- UI checkboxes to filter Module Statistics table by priority
- Supports multiple priority selection (P0, P1, P2, P3, UNKNOWN)
- "Clear Filters" button to reset
- Query parameter: `?priorities=P0,P1`

---

## Breaking Changes

### API Response Schema Change

**Endpoint:** `GET /api/v1/dashboard/summary/{release}/__all__`

**Breaking Change:** The `ModuleBreakdownSchema` no longer includes `job_id` field.

**Before:**
```json
{
  "module_breakdown": [
    {
      "module_name": "routing",
      "job_id": "215",          // ❌ REMOVED
      "total": 100,
      "passed": 95,
      "failed": 5,
      ...
    }
  ]
}
```

**After:**
```json
{
  "module_breakdown": [
    {
      "module_name": "routing",   // Now path-based
      "total": 100,
      "passed": 95,
      "failed": 5,
      ...
    }
  ]
}
```

**Reason:** Module breakdown now aggregates stats across ALL jobs for a parent_job_id, filtered by testcase_module. The `job_id` field is no longer meaningful since one module's tests may span multiple Jenkins jobs.

### Module List Changes

**Endpoint:** `GET /api/v1/dashboard/{release}/modules`

**Before:**
- Returned Jenkins job modules from `modules` table
- Had `created_at` timestamp from database

**After:**
- Returns path-derived modules from `test_results.testcase_module` (distinct values)
- `created_at` is now current timestamp (not from database)

**Impact:** If you're relying on module creation timestamps, this information is no longer available for path-based modules.

---

## Database Changes

### New Field: `testcase_module`

**Table:** `test_results`

**Migration:** `alembic/versions/e145675f4e76_add_testcase_module_field_to_test_.py`

```sql
ALTER TABLE test_results ADD COLUMN testcase_module VARCHAR(100);
CREATE INDEX ix_test_results_testcase_module ON test_results (testcase_module);
```

### Backfilling Existing Data

For existing test results, run the backfill script to populate `testcase_module`:

```bash
# Dry run first to preview changes
python scripts/backfill_testcase_modules.py --dry-run --show-unparseable

# Apply changes
python scripts/backfill_testcase_modules.py

# Expected output:
# ✅ Backfill complete!
#    Updated: 6917 test results
#    Skipped: 0 test results (no matching pattern)
#    Coverage: 100.0%
```

**What it does:**
- Parses `file_path` for each test result
- Extracts module from pattern: `data_plane/tests/{module_name}/*`
- Updates `testcase_module` field
- Shows verification statistics

---

## Migration Steps

### For Application Deployments

1. **Pull Latest Code:**
   ```bash
   git pull origin feature/priority-filter-module-stats
   ```

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Database Migration:**
   ```bash
   alembic upgrade head
   ```

4. **Backfill Existing Data:**
   ```bash
   # Dry run first
   python scripts/backfill_testcase_modules.py --dry-run

   # Review output, then apply
   python scripts/backfill_testcase_modules.py
   ```

5. **Restart Application:**
   ```bash
   ./start.sh
   # OR
   systemctl restart regression-tracker
   ```

6. **Verify:**
   - Navigate to Dashboard > 7.0 > All Modules
   - Verify module names look correct
   - Test priority filtering checkboxes

### For API Consumers

If you consume the API endpoints, update your code:

1. **Remove `job_id` field dependency:**
   ```python
   # Before
   for module in response['module_breakdown']:
       job_id = module['job_id']  # ❌ No longer exists

   # After
   for module in response['module_breakdown']:
       # Use module_name only
       module_name = module['module_name']
   ```

2. **Update module name expectations:**
   - Module names are now path-based (e.g., "routing", "business_policy")
   - They may differ from Jenkins job module names
   - Use the new module list endpoint to get current modules

3. **Test priority filtering:**
   ```bash
   # Filter by priorities
   curl "http://localhost:8000/api/v1/dashboard/summary/7.0/__all__?priorities=P0,P1"
   ```

---

## Validation & Testing

### Verify Backfill Success

After running the backfill script, verify with SQL:

```sql
-- Check coverage
SELECT
    COUNT(*) as total,
    COUNT(testcase_module) as with_module,
    COUNT(testcase_module) * 100.0 / COUNT(*) as coverage_pct
FROM test_results;

-- View module distribution
SELECT
    testcase_module,
    COUNT(*) as test_count
FROM test_results
WHERE testcase_module IS NOT NULL
GROUP BY testcase_module
ORDER BY test_count DESC;

-- Find tests without module
SELECT file_path
FROM test_results
WHERE testcase_module IS NULL
LIMIT 10;
```

Expected: ~100% coverage for tests following `data_plane/tests/*` pattern.

### Test Priority Filtering

1. Navigate to: `http://localhost:8000/`
2. Select Release: **7.0**
3. Select Module: **All Modules**
4. Check priority boxes: **P0**, **P1**
5. Verify:
   - Module Statistics table updates
   - Only P0/P1 tests are counted
   - "Clear Filters" button appears
   - URL includes `?priorities=P0,P1`

### API Testing

```bash
# Test module list (path-based)
curl http://localhost:8000/api/v1/dashboard/7.0/modules

# Test summary with priority filter
curl "http://localhost:8000/api/v1/dashboard/summary/7.0/__all__?priorities=P0,P1,UNKNOWN"

# Verify no job_id in module_breakdown
curl http://localhost:8000/api/v1/dashboard/summary/7.0/__all__ | jq '.module_breakdown[0]'
# Should NOT contain "job_id" key
```

---

## Rollback Plan

If issues arise, you can rollback:

1. **Revert Database Migration:**
   ```bash
   alembic downgrade -1
   ```

2. **Revert Code:**
   ```bash
   git checkout main
   pip install -r requirements.txt
   ```

3. **Restart Application:**
   ```bash
   systemctl restart regression-tracker
   ```

**Note:** Rolling back will **remove** the `testcase_module` column and index. You'll need to re-run the backfill if you upgrade again.

---

## Troubleshooting

### Issue: Low Coverage After Backfill

**Symptoms:** Backfill shows <100% coverage

**Cause:** Test files don't follow `data_plane/tests/{module}/*` pattern

**Solution:**
1. Run with `--show-unparseable` to see problem paths:
   ```bash
   python scripts/backfill_testcase_modules.py --dry-run --show-unparseable
   ```

2. Review unparseable paths - they may be:
   - Control plane tests (expected to have NULL module)
   - Non-standard test locations
   - Legacy tests with different structure

3. These can be ignored if they're not data plane tests

### Issue: Module Names Look Wrong

**Symptoms:** Module names don't match expectations

**Cause:** Mismatch between file path structure and expected modules

**Solution:**
1. Check `module_cross_contamination_report.txt` for expected modules
2. Verify test file paths follow standard structure
3. If module names need adjustment, update file paths or modify `extract_module_from_path()` function

### Issue: Priority Filtering Not Working

**Symptoms:** Checkboxes don't filter results

**Cause:** Browser cache or API issues

**Solution:**
1. Hard refresh: Ctrl+Shift+R (Windows/Linux) or Cmd+Shift+R (Mac)
2. Check browser console for errors
3. Verify API call includes `?priorities=` parameter
4. Check backend logs for validation errors

---

## Performance Considerations

### Query Optimization

This PR includes optimizations to prevent N+1 query problems:

- **Before:** Individual queries per job (10-20 queries)
- **After:** Single aggregation query per endpoint

**Improvement:** ~10x faster for module statistics calculations

### Caching

Module breakdown results are cached (default: 5 minutes). After priority filter changes:

- Cache is automatically invalidated
- Results may take ~1-2 seconds to calculate on first load
- Subsequent loads use cached results

---

## FAQ

**Q: Will this affect my existing dashboards?**

A: Yes, if you have external tools consuming the API. Update them to handle the missing `job_id` field in module breakdown.

**Q: Do I need to re-import my Jenkins data?**

A: No. The backfill script updates existing test results. Future imports automatically populate `testcase_module`.

**Q: Can I still use Jenkins module names?**

A: No. The application now exclusively uses path-based modules for consistency. This ensures tests always appear in their correct module.

**Q: What happens to tests without a testcase_module?**

A: They're excluded from path-based views (Dashboard, Trends). They still exist in the database and can be queried directly by job_id.

**Q: Is there a performance impact?**

A: Minimal. The indexed `testcase_module` column provides fast filtering. Query optimizations actually improve performance over the previous implementation.

---

## Support

For issues or questions:
- GitHub Issues: https://github.com/akshay1-arista/regression-tracker-web/issues
- PR Discussion: https://github.com/akshay1-arista/regression-tracker-web/pull/18

---

## Summary Checklist

Deploying PR #18? Verify:

- [ ] Database migration applied (`alembic upgrade head`)
- [ ] Backfill script executed successfully
- [ ] Coverage ≥95% for `testcase_module` field
- [ ] Application restarted
- [ ] Dashboard shows path-based modules
- [ ] Priority filtering works (P0, P1, P2, P3, UNKNOWN)
- [ ] API consumers updated (removed `job_id` dependency)
- [ ] Monitoring/alerts updated if needed
