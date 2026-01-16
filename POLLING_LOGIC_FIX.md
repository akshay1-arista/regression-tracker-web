# Jenkins Polling Logic Fix

## Problem
The original polling logic was **checking for new module jobs within a FIXED main job build** (e.g., job 14). This meant it could never detect when new main job builds (15, 16, 17, etc.) were created.

## Solution
Changed the polling to **detect NEW main job builds** and import all module jobs from each new build.

---

## How It Works Now

### 1. Configure Release with Main Job URL (NO Build Number)
When adding a release in the Admin interface, provide the **main job URL WITHOUT a specific build number**:

```
CORRECT:
https://jenkins2.vdev.sjc.aristanetworks.com/job/QA_Release_7.0/job/SILVER/job/DATA_PLANE/job/MODULE-RUN-ESXI-IPV4-ALL/

WRONG (old way):
https://jenkins2.vdev.sjc.aristanetworks.com/job/QA_Release_7.0/job/SILVER/job/DATA_PLANE/job/MODULE-RUN-ESXI-IPV4-ALL/14/
```

### 2. Polling Workflow

Every 15 minutes (configurable), the system:

1. **Query Jenkins API** for all builds of the main job:
   ```
   GET .../MODULE-RUN-ESXI-IPV4-ALL/api/json?tree=builds[number]
   Returns: [{"number": 17}, {"number": 16}, {"number": 15}, {"number": 14}, ...]
   ```

2. **Filter to new builds** using `release.last_processed_build`:
   - If `last_processed_build = 14`, only process builds [15, 16, 17]

3. **For each new main job build**:
   - Download `build_map.json` from `.../MODULE-RUN-ESXI-IPV4-ALL/15/`
   - Parse module job mappings (e.g., `{"BUSINESS_POLICY_ESXI": 8, "ROUTING_ESXI": 12, ...}`)
   - Download artifacts for each module job
   - Import test results into database
   - Update `release.last_processed_build = 15`

4. **Repeat for next build** (16, 17, etc.)

---

## Database Changes

### New Column: `releases.last_processed_build`
- **Type**: Integer
- **Default**: 0
- **Purpose**: Tracks the highest main job build number we've processed
- **Migration**: `a1b2c3d4e5f6_add_last_processed_build_to_releases.py`

---

## Code Changes

### 1. JenkinsClient.get_job_builds() - NEW METHOD
File: [app/services/jenkins_service.py](app/services/jenkins_service.py)

```python
def get_job_builds(self, job_url: str, min_build: int = 0) -> List[int]:
    """
    Get list of all build numbers for a Jenkins job.

    Args:
        job_url: Jenkins job URL (without build number)
        min_build: Only return builds greater than this number

    Returns:
        List of build numbers, sorted descending (newest first)
    """
```

Queries: `{job_url}/api/json?tree=builds[number]`

### 2. poll_release() - UPDATED LOGIC
File: [app/tasks/jenkins_poller.py](app/tasks/jenkins_poller.py)

**Before:**
- Download build_map.json from FIXED build (e.g., job 14)
- Detect new module jobs within that single build

**After:**
- Get ALL main job builds from Jenkins API
- Filter to builds > `last_processed_build`
- Process each new main job build:
  - Download its build_map.json
  - Import all module jobs
  - Update `last_processed_build`

---

## Example Scenario

### Initial State
```
Database:
  Release: 7.0.0.0
  jenkins_job_url: ".../MODULE-RUN-ESXI-IPV4-ALL/"
  last_processed_build: 14
```

### Jenkins Has New Builds
```
Jenkins API returns: [17, 16, 15, 14, 13, ...]
```

### Polling Process

**Cycle 1 (15 minutes later):**
1. Query Jenkins: Get builds [17, 16, 15] (> 14)
2. Process build 15:
   - Download `.../MODULE-RUN-ESXI-IPV4-ALL/15/artifact/build_map.json`
   - Extract: `{"BUSINESS_POLICY_ESXI": 8, "ROUTING_ESXI": 12, ...}`
   - Download artifacts for each module
   - Import to database
   - Update `last_processed_build = 15`
3. Process build 16: (same steps)
4. Process build 17: (same steps)

**Result:**
```
Database:
  last_processed_build: 17
  New Jobs Imported: All modules from builds 15, 16, 17
```

**Cycle 2 (30 minutes later):**
1. Query Jenkins: No new builds (still at 17)
2. Log: "No new builds found (last processed: 17)"

**Cycle 3 (45 minutes later, after Jenkins runs build 18):**
1. Query Jenkins: Get build [18] (> 17)
2. Process build 18
3. Update `last_processed_build = 18`

---

## Migration Instructions

### 1. Run Database Migration
```bash
cd regression-tracker-web
alembic upgrade head
```

This adds the `last_processed_build` column to existing releases (defaults to 0).

### 2. Update Release URLs
For each existing release in the Admin interface:
1. Navigate to Admin page
2. Edit the release
3. **Remove the build number** from `jenkins_job_url`:
   - Before: `.../MODULE-RUN-ESXI-IPV4-ALL/14/`
   - After: `.../MODULE-RUN-ESXI-IPV4-ALL/`

### 3. Set Initial Build Number (Optional)
If you want to skip re-importing old builds, manually set `last_processed_build`:

```sql
UPDATE releases
SET last_processed_build = 14
WHERE name = '7.0.0.0';
```

This tells the system "we've already processed builds up to 14, start from 15."

### 4. Verify Polling
Check logs to confirm polling detects new builds:

```bash
tail -f logs/application.log | grep "Polling release"
```

Expected output:
```
2024-01-16 12:00:00 - INFO - Polling release: 7.0.0.0
2024-01-16 12:00:01 - INFO - Found 3 new main job builds for 7.0.0.0: [17, 16, 15]
2024-01-16 12:00:02 - INFO - Processing main job build 15...
2024-01-16 12:00:05 - INFO - Found 12 modules in build 15
...
```

---

## Benefits

1. **Automatic Detection**: No need to manually update release URLs when new builds appear
2. **Incremental Processing**: Only downloads NEW builds, skips existing data
3. **Resilient**: Tracks progress per-release, survives restarts
4. **Accurate**: Processes builds in chronological order (oldest first)
5. **Efficient**: Uses Jenkins API instead of guessing build numbers

---

## Testing

### 1. Test New Build Detection
```python
# Simulate new Jenkins build appearing
# 1. Check current last_processed_build
SELECT name, last_processed_build FROM releases;

# 2. Wait for polling cycle (or manually trigger)
# 3. Verify new build detected in logs
# 4. Check database updated
SELECT name, last_processed_build FROM releases;
```

### 2. Test Manual Download
1. Navigate to Admin page
2. Trigger manual download with main job URL (no build number)
3. Verify it downloads from the LATEST build

---

## Files Modified

1. **app/models/db_models.py**
   - Added `last_processed_build` column to `Release` model

2. **app/services/jenkins_service.py**
   - Added `get_job_builds()` method to query Jenkins API

3. **app/tasks/jenkins_poller.py**
   - Rewrote `poll_release()` to detect new main job builds

4. **alembic/versions/a1b2c3d4e5f6_add_last_processed_build_to_releases.py**
   - Database migration script

---

## Rollback (if needed)

If issues occur, revert the migration:

```bash
cd regression-tracker-web
alembic downgrade -1
```

This removes the `last_processed_build` column and reverts to the previous schema.
