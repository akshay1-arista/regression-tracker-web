# Parent Job URL and Comparison Fix

**Date:** 2026-02-23
**Issue:** Dashboard showing incorrect comparison deltas and wrong Jenkins URLs for 6.4/6.1 jobs

## Problems Fixed

### 1. Incorrect Comparison Deltas

**Problem:**
- Dashboard was comparing job 74 to an intervening job (73) instead of the chronologically previous job (71)
- This resulted in incorrect delta calculations (showing -138 instead of -223)

**Root Cause:**
- `get_previous_parent_job_id()` was using database import timestamps (`created_at`) instead of actual Jenkins execution times (`executed_at`)
- This failed when jobs were imported out of order or when multiple releases share the same Jenkins job URL

**Solution:**
- Updated `get_previous_parent_job_id()` to sort parent jobs by `executed_at` (with fallback to `created_at`)
- Ensures correct chronological ordering even when multiple releases use the same Jenkins URL

**Files Changed:**
- [app/services/data_service.py](app/services/data_service.py) (lines 1380-1452)

### 2. Incorrect Parent Job URLs for 6.4 and 6.1

**Problem:**
- Newer jobs for releases 6.4 and 6.1 (jobs 73, 55, 64, etc.) were using the old release-specific URLs:
  - `https://jenkins2.../QA_Release_6.4/.../MODULE-RUN-ESXI-IPV4-ALL/`
  - `https://jenkins2.../QA_Release_6.1/.../MODULE-RUN-ESXI-IPV4-ALL/`
- But these jobs actually run under the shared 7.0 URL:
  - `https://jenkins2.../QA_Release_7.0/.../MODULE-RUN-ESXI-IPV4-ALL/`

**Root Cause:**
- Parent job URLs were constructed using `release.jenkins_job_url` from the `releases` table
- This URL was static and didn't reflect that newer jobs from multiple releases now share the same Jenkins job URL

**Solution:**
- Created `get_parent_job_url()` helper function that extracts the correct base URL from actual job records
- Updated `_aggregate_jobs_for_parent()` to extract parent job URL from the first job's `jenkins_url`
- Updated `get_parent_jobs_with_dates()` to use the helper function
- Updated admin.py to extract URL from actual job records

**Files Changed:**
- [app/services/data_service.py](app/services/data_service.py) (lines 1455-1513, 1549-1638, 1360-1377)
- [app/routers/admin.py](app/routers/admin.py) (lines 1023-1040)

## Verification

### Test Results

**6.4 Parent Job URLs:**
- Job 73 → `QA_Release_7.0` ✓ (newer job, shared URL)
- Job 55 → `QA_Release_7.0` ✓ (newer job, shared URL)
- Job 219 → `QA_Release_6.4` ✓ (older job, release-specific URL)
- Job 217 → `QA_Release_6.4` ✓ (older job, release-specific URL)

**6.1 Parent Job URLs:**
- Job 64 → `QA_Release_7.0` ✓ (newer job, shared URL)
- Job 277 → `QA_Release_6.1` ✓ (older job, release-specific URL)
- Job 276 → `QA_Release_6.1` ✓ (older job, release-specific URL)

**7.0 Parent Job URLs:**
- Job 74 → `QA_Release_7.0` ✓
- Job 71 → `QA_Release_7.0` ✓

**Comparison Deltas:**
- Job 74 compared to Job 71 (chronologically previous)
- Delta: 5621 - 5844 = **-223** ✓ (previously showed -138)

### Test Scripts

Two verification scripts were created:

1. **[scripts/verify_comparison_fix.py](scripts/verify_comparison_fix.py)**
   - Verifies comparison logic uses execution time
   - Shows chronological ordering of parent jobs
   - Displays delta calculations

2. **[scripts/test_parent_job_urls.py](scripts/test_parent_job_urls.py)**
   - Tests parent job URL extraction for multiple releases
   - Verifies correct URL patterns for newer vs older jobs
   - Compares helper function output with aggregated stats output

### Automated Tests

All existing tests pass:
```bash
pytest tests/test_services.py -k "parent_job"
# Result: 9 passed, 44 deselected
```

## Technical Details

### URL Extraction Algorithm

```python
# Extract base URL from job's jenkins_url
# Input:  https://.../job/QA_Release_7.0/.../job/MODULE-NAME/123/
# Output: https://.../job/QA_Release_7.0/.../MODULE-RUN-ESXI-IPV4-ALL/74/

1. Remove job number suffix: .../MODULE-NAME/123/ → .../MODULE-NAME/
2. Go up one directory level: .../MODULE-NAME/ → .../DATA_PLANE/
3. Append parent_job_id: .../DATA_PLANE/ → .../DATA_PLANE/74/
```

### Fallback Behavior

If URL extraction fails (no jobs found, malformed URLs), the system falls back to using `release.jenkins_job_url` from the database. This ensures backward compatibility with older data.

## Migration Notes

**No database migration required.** The fix uses existing data:
- Individual job records already contain correct `jenkins_url` values
- The fix extracts parent job URLs dynamically from these existing records

## Impact

**User-Visible Changes:**
- Dashboard now shows correct comparison deltas
- Parent job links for 6.4/6.1 now point to correct Jenkins URLs (7.0 for newer jobs, release-specific for older jobs)

**Backend Changes:**
- Parent job comparison now chronological (execution-time based)
- Parent job URLs now dynamic (extracted from actual job records)
- Improved support for multi-release Jenkins job sharing

## Backward Compatibility

✅ **Fully backward compatible:**
- Older jobs continue to use release-specific URLs
- Fallback to `release.jenkins_job_url` if extraction fails
- All existing tests pass
- No schema changes required
