# Version Tracking Feature

## Overview
Jobs now automatically extract and store version information from the Jenkins job title, enabling filtering and organization by version.

## How It Works

### Version Extraction

When the polling system downloads a job from Jenkins, it:

1. **Fetches job metadata** from Jenkins API:
   ```
   GET .../MODULE-RUN-ESXI-IPV4-ALL/15/api/json?tree=displayName,url,number...
   ```

2. **Extracts version** from displayName using regex:
   ```
   Job Title: "REL: Release_7.0 | VER: 7.0.0.0 | MOD: FULL-RUN | PRIO: ALL | master"
   Extracted Version: "7.0.0.0"
   ```

3. **Stores version** in the `jobs.version` column

### Pattern Recognition

The system uses regex to extract version numbers in the format `VER: X.X.X.X`:

```python
Pattern: r'VER:\s*(\d+\.\d+\.\d+\.\d+)'
Matches: "VER: 7.0.0.0", "VER:7.0.0.0", "VER:  7.0.0.0"
```

---

## Database Changes

### New Column: `jobs.version`
- **Type**: VARCHAR(50)
- **Nullable**: Yes (existing jobs without version)
- **Example Values**: "7.0.0.0", "6.9.5.2", etc.

### Schema

```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    module_id INTEGER NOT NULL,
    job_id VARCHAR(20) NOT NULL,

    -- Statistics
    total INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    error INTEGER DEFAULT 0,
    pass_rate FLOAT DEFAULT 0.0,

    -- Metadata
    jenkins_url VARCHAR(500),
    version VARCHAR(50),        -- NEW!
    created_at DATETIME,
    downloaded_at DATETIME,

    FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE CASCADE
);
```

---

## Usage Examples

### 1. Query Jobs by Version

```sql
-- Get all jobs for version 7.0.0.0
SELECT j.job_id, m.name AS module, j.pass_rate, j.version
FROM jobs j
JOIN modules m ON j.module_id = m.id
WHERE j.version = '7.0.0.0'
ORDER BY j.created_at DESC;
```

### 2. Compare Versions

```sql
-- Compare pass rates between versions
SELECT
    j.version,
    AVG(j.pass_rate) AS avg_pass_rate,
    COUNT(*) AS job_count
FROM jobs j
WHERE j.version IN ('7.0.0.0', '6.9.5.2')
GROUP BY j.version;
```

### 3. Filter API Requests (Future Enhancement)

```
GET /api/v1/jobs/7.0.0.0/business_policy?version=7.0.0.0
```

---

## Automatic Version Tracking

The polling system **automatically extracts and stores version** during import:

```python
# In jenkins_poller.py (poll_release function)

# 1. Fetch job info from Jenkins
job_info = client.get_job_info(job_url)
display_name = job_info.get('displayName', '')

# 2. Extract version from title
from app.services.jenkins_service import extract_version_from_title
version = extract_version_from_title(display_name)

# 3. Import with version
import_service = ImportService(db)
import_service.import_job(
    release.name,
    module_name,
    job_id,
    jenkins_url=job_url,
    version=version  # ← Stored in database
)
```

---

## Migration

The migration was applied successfully:

```bash
alembic upgrade head

# Output:
# Running upgrade a1b2c3d4e5f6 -> b2c3d4e5f6g7, add version to jobs
```

**Existing jobs**: Will have `version = NULL` until re-imported or updated
**New jobs**: Automatically populated from Jenkins job title

---

## Future Enhancements

### 1. Frontend Filtering

Add version dropdown in dashboard and trends views:

```html
<!-- In templates/dashboard.html -->
<select x-model="selectedVersion" @change="loadJobs()">
    <option value="">All Versions</option>
    <option value="7.0.0.0">7.0.0.0</option>
    <option value="6.9.5.2">6.9.5.2</option>
</select>
```

### 2. API Filtering

Update routers to accept version filter:

```python
@router.get("/jobs/{release}/{module}")
async def get_jobs(
    release: str,
    module: str,
    version: Optional[str] = None,  # ← New filter
    db: Session = Depends(get_db)
):
    query = db.query(Job).join(Module).join(Release)...

    if version:
        query = query.filter(Job.version == version)

    return query.all()
```

### 3. Version Statistics

Show version-specific metrics:

```python
# Group jobs by version
versions = db.query(
    Job.version,
    func.count(Job.id).label('job_count'),
    func.avg(Job.pass_rate).label('avg_pass_rate')
).group_by(Job.version).all()
```

### 4. Version Comparison View

Create a page to compare test results across versions side-by-side.

---

## Troubleshooting

### Version Not Extracted

**Issue**: Jobs show `version = NULL`

**Causes**:
1. Job title doesn't contain "VER: X.X.X.X" pattern
2. Jenkins API request failed
3. Regex pattern mismatch

**Debug**:
```bash
# Check logs for version extraction
grep "Extracted version" logs/application.log

# Verify job title format in Jenkins
curl "https://jenkins.../job/MODULE/.../api/json?tree=displayName"
```

### Update Existing Jobs

To backfill versions for existing jobs, you can:

1. **Re-import from logs** (version won't be available unless fetched from Jenkins)
2. **Manually update** if you know the version:
   ```sql
   UPDATE jobs SET version = '7.0.0.0'
   WHERE module_id IN (
       SELECT id FROM modules WHERE release_id = (
           SELECT id FROM releases WHERE name = '7.0.0.0'
       )
   );
   ```

3. **Fetch from Jenkins API** (requires custom script):
   ```python
   for job in jobs_without_version:
       job_info = jenkins_client.get_job_info(job.jenkins_url)
       version = extract_version_from_title(job_info['displayName'])
       job.version = version
       db.commit()
   ```

---

## Files Modified

1. **app/models/db_models.py**
   - Added `version` column to `Job` model

2. **app/services/jenkins_service.py**
   - Added `get_job_info()` method to fetch job metadata
   - Added `extract_version_from_title()` to parse version from displayName

3. **app/services/import_service.py**
   - Updated `get_or_create_job()` to accept and store version
   - Updated `import_job()` to accept version parameter
   - Updated `ImportService.import_job()` to pass version

4. **app/tasks/jenkins_poller.py**
   - Modified `poll_release()` to fetch job info and extract version
   - Pass version to import service

5. **alembic/versions/b2c3d4e5f6g7_add_version_to_jobs.py**
   - Migration script to add version column

---

## Benefits

1. **Better Organization**: Filter and view jobs by specific versions
2. **Trend Analysis**: Compare test stability across versions
3. **Regression Detection**: Identify when tests started failing in specific versions
4. **Release Management**: Track which versions have been tested
5. **Historical Data**: Maintain version context for long-term analysis

---

## Example Queries

### Find Flaky Tests by Version

```sql
SELECT
    tr.test_name,
    j.version,
    COUNT(CASE WHEN tr.status = 'FAILED' THEN 1 END) AS fail_count,
    COUNT(CASE WHEN tr.status = 'PASSED' THEN 1 END) AS pass_count
FROM test_results tr
JOIN jobs j ON tr.job_id = j.id
WHERE j.version = '7.0.0.0'
GROUP BY tr.test_name, j.version
HAVING fail_count > 0 AND pass_count > 0
ORDER BY fail_count DESC;
```

### Version-specific Pass Rate Trend

```sql
SELECT
    DATE(j.created_at) AS test_date,
    j.version,
    AVG(j.pass_rate) AS avg_pass_rate
FROM jobs j
WHERE j.version IS NOT NULL
GROUP BY DATE(j.created_at), j.version
ORDER BY test_date DESC, j.version;
```

---

## Next Steps

To fully utilize the version tracking feature:

1. **Add Frontend Filters**: Implement version dropdown in UI
2. **Update API Endpoints**: Add version query parameter support
3. **Create Version Comparison View**: Show side-by-side comparisons
4. **Add Version to Dashboard**: Display version info prominently
5. **Backfill Existing Data**: Update version for historical jobs (optional)
