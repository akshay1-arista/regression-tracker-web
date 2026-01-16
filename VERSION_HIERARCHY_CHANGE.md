# Version Filtering Hierarchy Change

## Summary

**Changed the filtering hierarchy from `Release → Module → Version` to `Release → Version → Module`**

This makes version a **release-level attribute** rather than a module-level attribute, which is more intuitive and aligned with how software versioning works.

## Before vs After

### ❌ Old Hierarchy (Module → Version)
```
1. Select Release: "7.0"
2. Select Module: "business_policy"
3. Select Version: "7.0.0.0"
   ↳ Shows jobs for this specific module with this version
```

**Problem**: Users had to select a module first to see available versions, even though versions apply to the entire release.

### ✅ New Hierarchy (Version → Module)
```
1. Select Release: "7.0"
2. Select Version: "7.0.0.0" or "All Versions"
   ↳ Shows all versions across entire release
3. Select Module: "business_policy"
   ↳ Shows only modules that have jobs with selected version
4. View Dashboard
   ↳ Shows filtered data
```

**Benefit**: Versions are shown at release level, and module dropdown filters to show only relevant modules for the selected version.

---

## Technical Changes

### API Endpoints

| Endpoint | Before | After |
|----------|--------|-------|
| **Get Versions** | `GET /versions/{release}/{module}` | `GET /versions/{release}` |
| **Get Modules** | `GET /modules/{release}` | `GET /modules/{release}?version={version}` |
| **Get Summary** | `GET /summary/{release}/{module}?version={version}` | *(unchanged)* |

### Frontend Flow

**Before:**
```javascript
loadReleases() → loadModules() → loadVersions() → loadSummary()
```

**After:**
```javascript
loadReleases() → loadVersions() → loadModules() → loadSummary()
```

### Selector Order in UI

**Before:**
```html
[Release ▼] → [Module ▼] → [Version ▼]
```

**After:**
```html
[Release ▼] → [Version ▼] → [Module ▼]
```

---

## Implementation Details

### 1. Backend Changes

**File: `app/routers/dashboard.py`**

#### Changed: `/versions/{release}` (formerly `/versions/{release}/{module}`)
```python
@router.get("/versions/{release}", response_model=List[str])
async def get_versions(
    release: str = Path(...),
    db: Session = Depends(get_db)
):
    """Get all versions across entire release."""
    # Query all jobs in release for distinct versions
    versions = db.query(Job.version).join(Module).filter(
        Module.release_id == release_obj.id,
        Job.version.isnot(None)
    ).distinct().all()

    version_list = [v[0] for v in versions if v[0]]
    version_list.sort(reverse=True)  # Newest first
    return version_list
```

#### Updated: `/modules/{release}` (now accepts version filter)
```python
@router.get("/modules/{release}", response_model=List[ModuleResponse])
async def get_modules(
    release: str = Path(...),
    version: Optional[str] = Query(None),  # NEW
    db: Session = Depends(get_db)
):
    """Get modules for release, optionally filtered by version."""
    if version:
        # Return only modules that have jobs with this version
        modules = db.query(Module).join(Job).filter(
            Module.release_id == release_obj.id,
            Job.version == version
        ).distinct().all()
    else:
        # Return all modules
        modules = data_service.get_modules_for_release(db, release)

    return modules
```

### 2. Frontend Changes

**File: `static/js/dashboard.js`**

#### Updated: `loadVersions()` - now called after release selection
```javascript
async loadVersions() {
    // Fetch versions for entire release (no module needed)
    const response = await fetch(
        `/api/v1/dashboard/versions/${this.selectedRelease}`
    );
    this.versions = await response.json();

    this.selectedVersion = '';  // Reset to "All Versions"
    await this.loadModules();   // Load modules (with optional version filter)
}
```

#### Updated: `loadModules()` - now accepts version filter
```javascript
async loadModules() {
    // Build URL with optional version parameter
    let url = `/api/v1/dashboard/modules/${this.selectedRelease}`;
    if (this.selectedVersion) {
        url += `?version=${encodeURIComponent(this.selectedVersion)}`;
    }

    const response = await fetch(url);
    this.modules = await response.json();

    if (this.modules.length > 0) {
        this.selectedModule = this.modules[0].name;
        await this.loadSummary();
    }
}
```

**File: `templates/dashboard.html`**

#### Reordered Selectors
```html
<!-- 1. Release Selector -->
<select x-model="selectedRelease" @change="loadVersions()">
    <!-- Release options -->
</select>

<!-- 2. Version Selector -->
<select x-model="selectedVersion" @change="loadModules()">
    <option value="">All Versions</option>
    <!-- Version options -->
</select>

<!-- 3. Module Selector -->
<select x-model="selectedModule" @change="loadSummary()">
    <!-- Module options (filtered by version) -->
</select>
```

---

## User Experience

### Scenario 1: View all modules for a release
```
1. Select Release: "7.0"
2. Keep Version: "All Versions"
3. Module dropdown shows: all 12 modules
4. Select any module to view dashboard
```

### Scenario 2: Filter by specific version
```
1. Select Release: "7.0"
2. Select Version: "7.0.0.0"
3. Module dropdown shows: only "business_policy" (the only module with version 7.0.0.0)
4. Dashboard shows only jobs with version 7.0.0.0
```

### Scenario 3: Switch between versions
```
1. Currently viewing: Release "7.0", Version "7.0.0.0", Module "business_policy"
2. Change Version to: "6.9.5.2"
3. Module dropdown updates: shows modules with version 6.9.5.2
4. If "business_policy" doesn't have 6.9.5.2 jobs:
   → Automatically selects first available module
5. Dashboard updates with new version data
```

---

## Benefits

1. **More Intuitive**: Version is inherently a release-level concept
2. **Better Discovery**: Users see all versions in a release upfront
3. **Cleaner Filtering**: Module list automatically filters to relevant modules
4. **Consistent with Domain Model**: Matches how software versioning actually works
5. **Reduced Confusion**: No need to arbitrarily pick a module to see versions

---

## Database Notes

- Version is stored in the `jobs` table
- A module may have jobs with different versions
- A version may exist across multiple modules
- Versions are extracted from Jenkins job titles during polling

Example:
```sql
-- Release "7.0" has these versions across all modules:
SELECT DISTINCT j.version
FROM jobs j
JOIN modules m ON j.module_id = m.id
JOIN releases r ON m.release_id = r.id
WHERE r.name = '7.0' AND j.version IS NOT NULL;

Result: ["7.0.0.0", "6.9.5.2"]

-- For version "7.0.0.0", these modules have jobs:
SELECT DISTINCT m.name
FROM modules m
JOIN jobs j ON j.module_id = m.id
WHERE m.release_id = (SELECT id FROM releases WHERE name = '7.0')
  AND j.version = '7.0.0.0';

Result: ["business_policy"]
```

---

## Migration Notes

### Breaking Changes
- ❌ `/api/v1/dashboard/versions/{release}/{module}` endpoint removed
- ✅ Replaced with `/api/v1/dashboard/versions/{release}`

### Backward Compatibility
- ✅ `/api/v1/dashboard/summary/{release}/{module}?version={version}` unchanged
- ✅ `/api/v1/dashboard/modules/{release}` still works (just returns all modules when no version filter)

### Update Required
Frontend code must be updated to match new flow. Old frontend will break because:
1. It will try to call `/versions/{release}/{module}` which doesn't exist
2. It won't pass version filter to `/modules/{release}`

---

## Testing Checklist

- [ ] Select release → versions dropdown populates
- [ ] Select "All Versions" → all modules shown
- [ ] Select specific version → only modules with that version shown
- [ ] Change version → module list updates correctly
- [ ] Change module → dashboard data updates
- [ ] Version column shows in jobs table
- [ ] "All Versions" shows combined data across versions
- [ ] Specific version filters all dashboard components
- [ ] Auto-refresh maintains version selection
- [ ] Page reload preserves state (if implemented)

---

## Files Modified

1. `app/routers/dashboard.py` - API endpoint changes
2. `templates/dashboard.html` - Selector reordering
3. `static/js/dashboard.js` - Flow logic updates
4. `FRONTEND_VERSION_FILTERING.md` - Documentation update
5. `VERSION_HIERARCHY_CHANGE.md` - This document

---

## Summary

**The change makes version a first-class filter at the release level, providing a more intuitive and powerful way to explore test results across different software versions.**
