# Frontend Version Filtering Implementation

## Overview
Extended the dashboard to support filtering by version at the release level, with the hierarchy: **Release → Version → Module**.

This allows users to:
1. Select a release (e.g., "7.0")
2. Select a version (e.g., "7.0.0.0") - shows all versions across the release
3. Select a module - shows only modules that have jobs with the selected version
4. View filtered dashboard data

## Changes Made

### 1. Backend - Data Service Layer
**File**: `app/services/data_service.py`

Updated three functions to accept optional `version` parameter:

#### `get_jobs_for_module()`
- Added `version: Optional[str] = None` parameter
- Filters jobs by version when provided
- **Line 107-145**

#### `get_job_summary_stats()`
- Added `version: Optional[str] = None` parameter
- Passes version filter to `get_jobs_for_module()`
- **Line 175-222**

#### `get_pass_rate_history()`
- Added `version: Optional[str] = None` parameter
- Passes version filter to `get_jobs_for_module()`
- **Line 225-259**

### 2. Backend - API Endpoints
**File**: `app/routers/dashboard.py`

#### New Endpoint: Get Versions (Release-level)
```python
GET /api/v1/dashboard/versions/{release}
```
- Returns list of distinct versions across ALL modules in a release
- Sorted descending (newest first)
- **Changed from**: `/versions/{release}/{module}` (module-level)

#### Updated Endpoint: Get Modules (with version filter)
```python
GET /api/v1/dashboard/modules/{release}?version={version}
```
- Accepts optional `version` query parameter
- When version provided: returns only modules that have jobs with that version
- When version omitted: returns all modules for the release

#### Existing Endpoint: Get Summary
```python
GET /api/v1/dashboard/summary/{release}/{module}?version={version}
```
- Accepts optional `version` query parameter
- Filters all data (summary stats, recent jobs, pass rate history) by version

### 3. Frontend - Dashboard Template
**File**: `templates/dashboard.html`

#### Selector Order (Release → Version → Module)
**Lines 26-69**: Reordered selectors to match new hierarchy

1. **Release Selector** (Lines 27-38)
   - `@change="loadVersions()"` - loads versions for selected release

2. **Version Selector** (Lines 40-54)
   - `@change="loadModules()"` - loads modules filtered by version
   - Shows "All Versions" option
   - Disabled until versions are loaded

3. **Module Selector** (Lines 56-69)
   - `@change="loadSummary()"` - loads summary for selected module
   - Shows only modules that have jobs with selected version
   - Disabled until modules are loaded

#### Added Version Column to Jobs Table (Lines 129, 149)
- Added "Version" header in table
- Added version data cell: `<td x-text="job.version || 'N/A'"></td>`

### 4. Frontend - Dashboard JavaScript
**File**: `static/js/dashboard.js`

#### Added State Variables (Lines 11, 17)
```javascript
versions: [],          // List of available versions
selectedVersion: '',   // Selected version filter (empty = all)
```

#### Updated `loadVersions()` Function (Lines 58-79)
```javascript
async loadVersions() {
    // Fetch versions for entire release (all modules)
    const response = await fetch(
        `/api/v1/dashboard/versions/${this.selectedRelease}`
    );
    this.versions = await response.json();

    // Reset to "All Versions"
    this.selectedVersion = '';

    // Load modules (with optional version filter)
    await this.loadModules();
}
```
- **Changed from**: Requiring module parameter
- **Changed to**: Release-level version fetching
- Calls `loadModules()` instead of `loadSummary()`

#### Updated `loadModules()` Function (Lines 84-112)
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
- **Changed from**: No version filtering
- **Changed to**: Accepts version filter to show only relevant modules
- Calls `loadSummary()` after module selection

#### Updated `loadSummary()` (Lines 117-119)
```javascript
// Build URL with optional version parameter
let url = `/api/v1/dashboard/summary/${this.selectedRelease}/${this.selectedModule}`;
if (this.selectedVersion) {
    url += `?version=${encodeURIComponent(this.selectedVersion)}`;
}
```

## User Flow

### New Filtering Hierarchy: Release → Version → Module

1. **User selects a release** (e.g., "7.0")
   - System loads all versions across the entire release
   - Version dropdown populated
   - "All Versions" selected by default

2. **User selects a version** (e.g., "7.0.0.0" or "All Versions")
   - System loads modules that have jobs with selected version
   - If "All Versions": shows all modules
   - If specific version: shows only modules with jobs for that version
   - Module dropdown populated

3. **User selects a module** (e.g., "business_policy")
   - System loads summary data filtered by release, version (if selected), and module
   - Summary stats, recent jobs, and pass rate history all filtered
   - Dashboard displays filtered results

### Visual Indicators
- Version dropdown shows "All Versions" option (empty value)
- Version displayed in "Recent Jobs" table
- Jobs without version show "N/A"

## Database Support

### Schema
```sql
-- jobs table
version VARCHAR(50)  -- e.g., "7.0.0.0"
```

### Example Queries
```sql
-- Get all jobs for version 7.0.0.0
SELECT * FROM jobs WHERE version = '7.0.0.0';

-- Get distinct versions for module
SELECT DISTINCT version FROM jobs
WHERE module_id = ? AND version IS NOT NULL
ORDER BY version DESC;
```

## API Examples

### Get Versions for Release
```bash
GET /api/v1/dashboard/versions/7.0

Response:
["7.0.0.0", "6.9.5.2", "6.9.5.1"]
```
*Returns all distinct versions across all modules in release "7.0"*

### Get Modules for Release (All Versions)
```bash
GET /api/v1/dashboard/modules/7.0

Response:
[
  {"name": "business_policy", "release": "7.0", "created_at": "..."},
  {"name": "firewall", "release": "7.0", "created_at": "..."},
  {"name": "routing_module", "release": "7.0", "created_at": "..."}
]
```

### Get Modules for Release (Filtered by Version)
```bash
GET /api/v1/dashboard/modules/7.0?version=7.0.0.0

Response:
[
  {"name": "business_policy", "release": "7.0", "created_at": "..."}
]
```
*Returns only modules that have jobs with version "7.0.0.0"*

### Get Summary Filtered by Version
```bash
GET /api/v1/dashboard/summary/7.0.0.0/business_policy?version=7.0.0.0

Response:
{
  "release": "7.0.0.0",
  "module": "business_policy",
  "summary": {
    "total_jobs": 5,
    "latest_job": {...},
    "average_pass_rate": 95.2
  },
  "recent_jobs": [
    {
      "job_id": "15",
      "version": "7.0.0.0",
      "total": 150,
      "passed": 143,
      "failed": 7,
      "pass_rate": 95.3,
      "created_at": "2025-01-16T10:30:00Z"
    }
  ],
  "pass_rate_history": [...]
}
```

### Get Summary for All Versions
```bash
GET /api/v1/dashboard/summary/7.0.0.0/business_policy

Response:
{
  "summary": {
    "total_jobs": 25,  // All jobs regardless of version
    "average_pass_rate": 92.8
  },
  "recent_jobs": [...]  // All jobs, including those without version
}
```

## Testing Checklist

- [ ] Version dropdown populates correctly when module selected
- [ ] "All Versions" option shows all jobs
- [ ] Selecting specific version filters summary stats
- [ ] Selecting specific version filters recent jobs table
- [ ] Selecting specific version filters pass rate history chart
- [ ] Version column displays in jobs table
- [ ] Jobs without version show "N/A"
- [ ] Switching between versions updates dashboard immediately
- [ ] Switching modules resets version to "All Versions"
- [ ] Switching releases resets version to "All Versions"

## Related Files

- `app/services/data_service.py` - Database query layer
- `app/routers/dashboard.py` - API endpoints
- `templates/dashboard.html` - Dashboard UI template
- `static/js/dashboard.js` - Dashboard JavaScript logic
- `app/models/db_models.py` - Database models (version column)
- `app/services/jenkins_service.py` - Version extraction from Jenkins
- `app/tasks/jenkins_poller.py` - Automatic version capture during polling

## Next Steps (Optional Future Enhancements)

1. **Add version filtering to Trends page**
   - Update `templates/trends.html`
   - Update `static/js/trends.js`
   - Update `app/routers/trends.py`

2. **Add version filtering to Job Details page**
   - Update `templates/job_details.html`
   - Update `app/routers/jobs.py`

3. **Add version comparison view**
   - Side-by-side comparison of multiple versions
   - Highlight test differences between versions

4. **Add version analytics**
   - Regression detection between versions
   - Version-specific flaky test tracking
   - Version stability metrics
