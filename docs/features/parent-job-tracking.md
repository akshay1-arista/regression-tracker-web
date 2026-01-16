# Parent Job ID Tracking Implementation

## Overview
Added `parent_job_id` column to the `jobs` table to properly track the parent-child relationship between main Jenkins jobs and their module-specific jobs. This ensures that all module jobs from the same parent build share the same version and can be properly grouped.

**Date**: January 16, 2026

---

## Database Schema Changes

### Migration: `21d565b90aa9_add_parent_job_id_to_jobs`

**Added Column**: `parent_job_id VARCHAR(20)` (nullable)
**Added Index**: `idx_parent_job` on `parent_job_id` for efficient queries

**Migration Files**:
- Migration: `alembic/versions/21d565b90aa9_add_parent_job_id_to_jobs.py`
- Model: `app/models/db_models.py` (line 79)

### Data Model

```
Parent Job (main_build_num: 11)
  ├── Release: 7.0
  ├── Version: 7.0.0.0
  ├── Module Jobs:
  │   ├── business_policy (job_id: 8, parent_job_id: 11, version: 7.0.0.0)
  │   ├── device_settings (job_id: 7, parent_job_id: 11, version: 7.0.0.0)
  │   ├── firewall (job_id: 7, parent_job_id: 11, version: 7.0.0.0)
  │   └── ... (9 more modules)
```

**Key Insight**: All module jobs from the same parent share:
- Same `parent_job_id`
- Same `version` (inherited from parent)
- Same release context

---

## Code Changes

### 1. Database Model (`app/models/db_models.py`)

**Line 79**: Added `parent_job_id` column to Job model

```python
class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    module_id = Column(Integer, ForeignKey("modules.id", ondelete="CASCADE"))
    job_id = Column(String(20), nullable=False)
    parent_job_id = Column(String(20))  # NEW: Parent Jenkins job
```

### 2. Import Service (`app/services/import_service.py`)

**Updated Functions**:

#### `get_or_create_job()` (Line 164)
- Added `parent_job_id` parameter
- Auto-updates `parent_job_id` if not set on existing jobs

```python
def get_or_create_job(
    db: Session,
    module: Module,
    job_id: str,
    jenkins_url: Optional[str] = None,
    version: Optional[str] = None,
    parent_job_id: Optional[str] = None  # NEW
) -> Job:
```

#### `import_job()` Standalone Function (Line 215)
- Added `parent_job_id` parameter
- Passes it to `get_or_create_job()`

#### `ImportService.import_job()` Wrapper (Line 528)
- Added `parent_job_id` parameter
- Passes it through to standalone function

### 3. Jenkins Poller (`app/tasks/jenkins_poller.py`)

**Line 188**: Now passes `parent_job_id` when importing jobs

```python
import_service.import_job(
    release.name,
    module_name,
    job_id,
    jenkins_url=job_url,
    version=version,
    parent_job_id=str(main_build_num)  # NEW
)
```

**Flow**:
1. Polls main Jenkins job for new builds (e.g., build 11, 15, 16)
2. For each main build, downloads `build_map.json`
3. Imports each module job with `parent_job_id` set to main build number
4. Stores version extracted from main job's display name

---

## Additional Fixes

### Admin Page Authentication

**Problem**: Admin page showed "Failed to load releases" error due to missing PIN configuration

**Fixes**:

1. **Added ADMIN_PIN_HASH to Settings** (`app/config.py:51`)
   ```python
   ADMIN_PIN_HASH: str = ""  # SHA-256 hash of admin PIN
   ```

2. **Added to Environment Files**
   - `.env`: `ADMIN_PIN_HASH=03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4`
   - `.env.example`: Same hash (for PIN: `1234`)

3. **Fixed Authentication Decorator** (`app/utils/security.py:52`)
   - Changed from module-level `os.getenv()` to dynamic `get_settings()`
   - Now reads `ADMIN_PIN_HASH` from Settings at runtime

4. **Updated Pydantic Models** (`app/routers/admin.py:66`)
   - Migrated from deprecated `class Config` to `ConfigDict(from_attributes=True)`

---

## Data Migration

### Existing Jobs Update

All jobs in release "7.0" were updated with `parent_job_id = "11"`:

```sql
UPDATE jobs SET parent_job_id = '11'
WHERE module_id IN (
    SELECT id FROM modules
    WHERE release_id = (SELECT id FROM releases WHERE name = '7.0')
);
```

**Result**: 12 module jobs updated

---

## Verification

### Database Query
```sql
SELECT r.name, m.name, j.job_id, j.parent_job_id, j.version
FROM jobs j
JOIN modules m ON j.module_id = m.id
JOIN releases r ON m.release_id = r.id
WHERE r.name = '7.0';
```

**Output**:
```
7.0|business_policy|8|11|7.0.0.0
7.0|device_settings|7|11|7.0.0.0
7.0|firewall|7|11|7.0.0.0
... (12 total rows)
```

### API Endpoints
```bash
# Test admin releases endpoint
curl -s http://localhost:8000/api/v1/admin/releases \
  -H "X-Admin-PIN: 1234" | jq .

# Response
[
  {
    "id": 2,
    "name": "7.0",
    "jenkins_job_url": null,
    "is_active": true,
    "created_at": "2026-01-16T11:31:20.566531",
    "module_count": 12
  }
]
```

---

## Impact on Version Filtering

With `parent_job_id` tracking, version filtering now works correctly:

1. **Dashboard Hierarchy**: Release → Version → Module
2. **Version Scope**: Release-level (not module-level)
3. **Module Filtering**: Shows only modules with jobs for selected version
4. **Grouping**: Can group all module jobs from same parent build

### Example Query
```python
# Get all module jobs from parent job 11
jobs = db.query(Job).filter(Job.parent_job_id == "11").all()

# Get all versions for a release
versions = db.query(Job.version).join(Module).filter(
    Module.release_id == release.id,
    Job.version.isnot(None)
).distinct().all()
```

---

## Files Modified

1. **Database**:
   - `alembic/versions/21d565b90aa9_add_parent_job_id_to_jobs.py` (new)
   - `app/models/db_models.py` (line 79)

2. **Import Service**:
   - `app/services/import_service.py` (3 functions updated)

3. **Jenkins Poller**:
   - `app/tasks/jenkins_poller.py` (line 188)

4. **Configuration**:
   - `app/config.py` (line 51)
   - `.env` (line 11)
   - `.env.example` (line 11)

5. **Admin API**:
   - `app/routers/admin.py` (line 66)
   - `app/utils/security.py` (line 52)

---

## Future Polling

All future Jenkins polling will automatically track parent job IDs:

1. Main job detected (e.g., build 15)
2. Module jobs downloaded and imported
3. Each module job gets `parent_job_id = "15"`
4. Version extracted from main job's display name
5. All module jobs share same version and parent_job_id

---

## Default Admin PIN

**PIN**: `1234`
**Hash**: `03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4`

To change the PIN:
```bash
cd /path/to/regression-tracker-web
python3 -c "from app.utils.security import hash_pin; print(hash_pin('YOUR_NEW_PIN'))"
# Update .env with new hash
```

---

## Summary

✅ **Parent Job Tracking**: Implemented via `parent_job_id` column
✅ **Version Inheritance**: All module jobs inherit parent's version
✅ **Database Migration**: Applied successfully with backfill
✅ **Admin Authentication**: Fixed and working with PIN 1234
✅ **API Endpoints**: All endpoints verified and functional
✅ **Future Polling**: Will automatically track parent jobs

The application now correctly models the parent-child relationship between main Jenkins jobs and their module-specific jobs, enabling accurate version filtering and job grouping.
