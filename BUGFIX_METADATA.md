# Bug Fix: Missing Metadata in Manual Download Endpoint

## Issue Description

The manual download endpoint (`POST /api/v1/jenkins/download`) was not extracting and storing critical metadata (version, parent_job_id, jenkins_url) when importing jobs to the database. This caused:

1. **Empty version dropdown** - Dashboard couldn't filter by version
2. **Missing parent job tracking** - Unable to trace jobs back to main build
3. **Broken Jenkins links** - No clickable links to view jobs in Jenkins

## Root Cause

In [app/routers/jenkins.py](app/routers/jenkins.py), the `run_download()` function was calling:

```python
# BEFORE (BUGGY)
import_service.import_job(release, module_name, module_job_id)
```

While the working endpoint (`download-selected`) was calling:

```python
# CORRECT
import_service.import_job(
    release,
    module_name,
    job_id,
    jenkins_url=job_url,      # ✅ Module job URL
    version=version,           # ✅ Extracted from displayName
    parent_job_id=str(build_number)  # ✅ Main build number
)
```

## Fix Applied

**File**: [app/routers/jenkins.py](app/routers/jenkins.py)
**Lines**: 597-663

### Changes Made

1. **Added regex import** (line 9):
   ```python
   import re
   ```

2. **Extract parent job ID from main job URL** (lines 597-603):
   ```python
   # Extract parent job ID from main job URL
   # Example URL: .../job/MODULE-RUN-ESXI-IPV4-ALL/216/
   parent_job_id = None
   parent_match = re.search(r'/(\d+)/?$', job_url.rstrip('/'))
   if parent_match:
       parent_job_id = parent_match.group(1)
       log_callback(f"Extracted parent job ID: {parent_job_id}")
   ```

3. **Extract version from each module job** (lines 629-637):
   ```python
   # Extract version from module job info (if available)
   version = None
   try:
       job_info = client.get_job_info(module_job_url)
       version = extract_version_from_title(job_info.get('displayName', ''))
       if version:
           log_callback(f"  Extracted version {version} for {module_name}")
   except Exception as e:
       log_callback(f"  Could not extract version for {module_name}: {e}")
   ```

4. **Updated import_job call with metadata** (lines 654-661):
   ```python
   import_service.import_job(
       release,
       module_name,
       module_job_id,
       jenkins_url=module_job_url,      # ✅ Now included
       version=version,                  # ✅ Now included
       parent_job_id=parent_job_id       # ✅ Now included
   )
   ```

## Impact

### Before Fix
- Jobs imported with NULL values:
  ```sql
  version = NULL
  parent_job_id = NULL
  jenkins_url = NULL
  ```
- Dashboard couldn't filter by version
- No traceability to main build

### After Fix
- Jobs imported with complete metadata:
  ```sql
  version = "6.4.2.0"
  parent_job_id = "216"
  jenkins_url = "https://jenkins2.vdev.sjc.aristanetworks.com/job/..."
  ```
- ✅ Version dropdown populated
- ✅ Parent job tracking works
- ✅ Jenkins links functional

## Testing

To verify the fix works:

1. **Start a new download**:
   ```bash
   curl -X POST http://localhost:8000/api/v1/jenkins/download \
     -H "Content-Type: application/json" \
     -d '{
       "release": "7.0",
       "job_url": "https://jenkins2.vdev.sjc.aristanetworks.com/job/QA_Release_7.0/job/SILVER/job/DATA_PLANE/job/MODULE-RUN-ESXI-IPV4-ALL/220/",
       "skip_existing": true
     }'
   ```

2. **Check logs for extraction messages**:
   - Look for: `Extracted parent job ID: 220`
   - Look for: `Extracted version 7.0.0.0 for business_policy`

3. **Verify database records**:
   ```sql
   SELECT job_id, version, parent_job_id, jenkins_url
   FROM jobs
   WHERE parent_job_id = '220';
   ```

4. **Check dashboard**:
   - Navigate to http://localhost:8000/
   - Select release "7.0"
   - Verify version "7.0.0.0" appears in dropdown
   - Select version and verify modules load

## Backward Compatibility

This fix is **fully backward compatible**:
- ✅ Existing jobs with NULL metadata continue to work
- ✅ "All Versions" filter still shows jobs with NULL version
- ✅ New jobs will have complete metadata
- ✅ Backfill script available for existing data

## Related Files

- **Fixed file**: [app/routers/jenkins.py](app/routers/jenkins.py)
- **Backfill script**: [backfill_6.4_metadata.py](backfill_6.4_metadata.py)
- **Import service**: [app/services/import_service.py](app/services/import_service.py)
- **Jenkins service**: [app/services/jenkins_service.py](app/services/jenkins_service.py)

## Backfilling Existing Data

For jobs imported before this fix, use the backfill script:

```bash
python3 backfill_6.4_metadata.py
```

Or create custom backfill for other releases by modifying:
- `RELEASE = "6.4"`
- `VERSION = "6.4.2.0"`
- `PARENT_JOB_ID = "216"`

## Version

- **Fix Date**: 2026-01-17
- **Fixed By**: Claude Code
- **Commit**: (pending)
- **Affected Releases**: All downloads using POST /api/v1/jenkins/download before this fix

## Future Improvements

Consider:
1. Add validation to ensure version is always extracted
2. Log warning if metadata extraction fails
3. Create API endpoint to backfill metadata for existing jobs
4. Add metadata quality report to admin page
