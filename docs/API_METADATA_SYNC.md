# Metadata Sync API Documentation

This document describes the new API endpoints for Git-based metadata synchronization added in PR #26.

## Table of Contents

- [Authentication](#authentication)
- [Endpoints](#endpoints)
  - [Trigger Sync for Single Release](#trigger-sync-for-single-release)
  - [Trigger Sync for All Releases](#trigger-sync-for-all-releases)
  - [Stream Sync Progress (SSE)](#stream-sync-progress-sse)
  - [Get Sync Status](#get-sync-status)
  - [Get Sync History](#get-sync-history)
  - [Configure Sync Schedule](#configure-sync-schedule)
- [Examples](#examples)

---

## Authentication

All metadata sync endpoints require admin PIN authentication via header:

```bash
X-Admin-PIN: your_admin_pin
```

---

## Endpoints

### Trigger Sync for Single Release

Manually trigger metadata synchronization for a specific release from its Git branch.

**Endpoint:** `POST /api/v1/admin/metadata-sync/trigger/{release_id}`

**Parameters:**
- `release_id` (path, required): ID of the release to sync

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/admin/metadata-sync/trigger/1 \
  -H "X-Admin-PIN: your_pin"
```

**Response (200 OK):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "started",
  "message": "Metadata sync started for release: 7.0.0.0"
}
```

**Error Responses:**

**404 Not Found:**
```json
{
  "detail": "Release 999 not found"
}
```

**400 Bad Request:**
```json
{
  "detail": "Release 5.4.0.0 has no git_branch configured"
}
```

**Use Cases:**
- Sync metadata after manual changes to test repository
- Update metadata for single release without affecting others
- Debug sync issues for specific release

---

### Trigger Sync for All Releases

Manually trigger metadata synchronization for all active releases with configured Git branches.

**Endpoint:** `POST /api/v1/admin/metadata-sync/trigger`

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/admin/metadata-sync/trigger \
  -H "X-Admin-PIN: your_pin"
```

**Response (200 OK):**
```json
{
  "job_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "status": "started",
  "message": "Metadata sync started for all active releases"
}
```

**Use Cases:**
- Sync all releases after repository reorganization
- Scheduled manual sync across all releases
- Bulk metadata refresh

---

### Stream Sync Progress (SSE)

Stream real-time progress updates for a metadata sync job using Server-Sent Events.

**Endpoint:** `GET /api/v1/admin/metadata-sync/progress/{job_id}`

**Parameters:**
- `job_id` (path, required): Job ID from trigger endpoint

**Request:**
```bash
curl -N http://localhost:8000/api/v1/admin/metadata-sync/progress/a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  -H "X-Admin-PIN: your_pin"
```

**Response (Server-Sent Events stream):**

```
event: connected
data: {"job_id": "a1b2c3d4-...", "message": "Connected to sync progress stream"}

event: log
data: {"message": "Starting metadata sync for release: 7.0.0.0"}

event: log
data: {"message": "Git branch: master"}

event: log
data: {"message": "Acquiring Git lock for branch 'master'"}

event: log
data: {"message": "Pulling latest changes from branch 'master'"}

event: log
data: {"message": "Discovered 1523 tests (2 files failed)"}

event: log
data: {"message": "Comparing with existing metadata"}

event: log
data: {"message": "Applying updates: 15 new, 103 updated, 7 removed"}

event: log
data: {"message": "Added 15/15 new tests"}

event: log
data: {"message": "Updated 103/103 tests"}

event: log
data: {"message": "Removed 7/7 tests"}

event: log
data: {"message": "=== Sync Complete ==="}

event: log
data: {"message": "Tests discovered: 1523"}

event: log
data: {"message": "Tests added: 15"}

event: log
data: {"message": "Tests updated: 103"}

event: log
data: {"message": "Tests removed: 7"}

event: log
data: {"message": "Files failed to parse: 2"}

event: log
data: {"message": "Sync completed successfully for 7.0.0.0"}

event: complete
data: {"status": "completed", "success": true, "error": null}
```

**Error Event:**
```
event: error
data: {"error": "Connection timeout"}
```

**Timeout Event:**
```
event: timeout
data: {"message": "Stream timeout after 5 minutes"}
```

**Use Cases:**
- Monitor long-running sync operations
- Debug sync issues in real-time
- Display progress in admin UI

**JavaScript Client Example:**
```javascript
const jobId = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
const eventSource = new EventSource(
  `/api/v1/admin/metadata-sync/progress/${jobId}`,
  { headers: { 'X-Admin-PIN': 'your_pin' } }
);

eventSource.addEventListener('connected', (e) => {
  const data = JSON.parse(e.data);
  console.log('Connected:', data.message);
});

eventSource.addEventListener('log', (e) => {
  const data = JSON.parse(e.data);
  console.log('Log:', data.message);
  // Append to UI log area
});

eventSource.addEventListener('complete', (e) => {
  const data = JSON.parse(e.data);
  console.log('Complete:', data);
  eventSource.close();
});

eventSource.addEventListener('error', (e) => {
  const data = JSON.parse(e.data);
  console.error('Error:', data.error);
  eventSource.close();
});
```

---

### Get Sync Status

Get current metadata sync configuration and last sync status.

**Endpoint:** `GET /api/v1/admin/metadata-sync/status`

**Request:**
```bash
curl http://localhost:8000/api/v1/admin/metadata-sync/status \
  -H "X-Admin-PIN: your_pin"
```

**Response (200 OK):**
```json
{
  "enabled": true,
  "interval_hours": 24.0,
  "next_run": "2026-02-07T10:30:00",
  "last_sync": {
    "id": 42,
    "status": "success",
    "sync_type": "scheduled",
    "git_commit_hash": "abc123def456",
    "tests_discovered": 1523,
    "tests_added": 15,
    "tests_updated": 103,
    "tests_removed": 7,
    "started_at": "2026-02-06T10:28:15",
    "completed_at": "2026-02-06T10:29:45",
    "error_message": null
  }
}
```

**Use Cases:**
- Check if automatic sync is enabled
- View last sync results
- Determine next scheduled sync time

---

### Get Sync History

Retrieve history of metadata sync operations.

**Endpoint:** `GET /api/v1/admin/metadata-sync/history`

**Query Parameters:**
- `limit` (optional, default: 50): Maximum number of logs to return

**Request:**
```bash
curl "http://localhost:8000/api/v1/admin/metadata-sync/history?limit=10" \
  -H "X-Admin-PIN: your_pin"
```

**Response (200 OK):**
```json
[
  {
    "id": 42,
    "status": "success",
    "sync_type": "manual",
    "git_commit_hash": "abc123def456",
    "tests_discovered": 1523,
    "tests_added": 15,
    "tests_updated": 103,
    "tests_removed": 7,
    "started_at": "2026-02-06T10:28:15",
    "completed_at": "2026-02-06T10:29:45",
    "error_message": null
  },
  {
    "id": 41,
    "status": "failed",
    "sync_type": "scheduled",
    "git_commit_hash": null,
    "tests_discovered": 0,
    "tests_added": 0,
    "tests_updated": 0,
    "tests_removed": 0,
    "started_at": "2026-02-05T10:00:00",
    "completed_at": "2026-02-05T10:00:15",
    "error_message": "GitCommandError: Connection timeout"
  }
]
```

**Use Cases:**
- Audit sync operations
- Investigate sync failures
- Track metadata changes over time

---

### Configure Sync Schedule

Update metadata sync scheduling configuration.

**Endpoint:** `POST /api/v1/admin/metadata-sync/configure`

**Request Body:**
```json
{
  "enabled": true,
  "interval_hours": 12.0
}
```

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/admin/metadata-sync/configure \
  -H "X-Admin-PIN: your_pin" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "interval_hours": 12.0}'
```

**Response (200 OK):**
```json
{
  "message": "Configuration updated successfully"
}
```

**Use Cases:**
- Enable/disable automatic sync
- Adjust sync frequency
- Pause sync during maintenance

---

## Examples

### Complete Workflow: Trigger and Monitor Sync

```bash
#!/bin/bash

ADMIN_PIN="your_pin"
BASE_URL="http://localhost:8000/api/v1/admin"

# 1. Trigger sync for release 1
echo "Triggering sync..."
RESPONSE=$(curl -s -X POST "$BASE_URL/metadata-sync/trigger/1" \
  -H "X-Admin-PIN: $ADMIN_PIN")

JOB_ID=$(echo $RESPONSE | jq -r '.job_id')
echo "Job ID: $JOB_ID"

# 2. Stream progress (blocks until complete)
echo "Monitoring progress..."
curl -N "$BASE_URL/metadata-sync/progress/$JOB_ID" \
  -H "X-Admin-PIN: $ADMIN_PIN"

# 3. Check final status
echo ""
echo "Checking final status..."
curl -s "$BASE_URL/metadata-sync/status" \
  -H "X-Admin-PIN: $ADMIN_PIN" | jq '.last_sync'
```

### Python Client Example

```python
import requests
import json
from typing import Iterator

class MetadataSyncClient:
    def __init__(self, base_url: str, admin_pin: str):
        self.base_url = base_url
        self.headers = {"X-Admin-PIN": admin_pin}

    def trigger_sync(self, release_id: int) -> str:
        """Trigger sync for a release, returns job_id."""
        response = requests.post(
            f"{self.base_url}/metadata-sync/trigger/{release_id}",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()["job_id"]

    def stream_progress(self, job_id: str) -> Iterator[dict]:
        """Stream progress updates as they arrive."""
        response = requests.get(
            f"{self.base_url}/metadata-sync/progress/{job_id}",
            headers=self.headers,
            stream=True
        )
        response.raise_for_status()

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    yield data

    def get_status(self) -> dict:
        """Get current sync status."""
        response = requests.get(
            f"{self.base_url}/metadata-sync/status",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

# Usage
client = MetadataSyncClient(
    base_url="http://localhost:8000/api/v1/admin",
    admin_pin="your_pin"
)

# Trigger and monitor sync
job_id = client.trigger_sync(release_id=1)
print(f"Started job: {job_id}")

for event in client.stream_progress(job_id):
    if "message" in event:
        print(f"  {event['message']}")
    elif "status" in event:
        print(f"Completed: {event['status']}")
        break

# Check final status
status = client.get_status()
print(f"Last sync: {status['last_sync']['status']}")
```

---

## Configuration

### Environment Variables

```bash
# Git Repository Settings
GIT_REPO_URL=git@github.com:velocloud-sdwan/velocloud.src.git
GIT_REPO_LOCAL_PATH=./data/git_repos/velocloud_src
GIT_REPO_BRANCH=master
GIT_REPO_SSH_KEY_PATH=/path/to/ssh/key
GIT_SSH_STRICT_HOST_KEY_CHECKING=true

# Test Discovery Paths (relative to repo root)
TEST_DISCOVERY_BASE_PATH=hapy/data_plane/tests
TEST_DISCOVERY_STAGING_CONFIG=hapy/data_plane/framework/staging/dp_staging.ini

# Sync Scheduling
METADATA_SYNC_ENABLED=false
METADATA_SYNC_INTERVAL_HOURS=24.0
METADATA_SYNC_ON_STARTUP=false
```

### Database Settings

Sync configuration is also stored in `app_settings` table:
- `METADATA_SYNC_ENABLED` (boolean)
- `METADATA_SYNC_INTERVAL_HOURS` (float)

Admin UI takes precedence over environment variables.

---

## Performance Characteristics

### Single Release Sync:
- **Small repos** (< 500 tests): 5-15 seconds
- **Medium repos** (500-5,000 tests): 15-60 seconds
- **Large repos** (> 5,000 tests): 60-180 seconds

### All Releases Sync:
- **Duration**: (single release time) × (number of active releases)
- **Recommendation**: Use per-release endpoint for faster targeted updates

### Progress Updates:
- SSE messages sent in real-time (< 100ms latency)
- Batching progress reported every 1,000 records
- 5-minute timeout for inactive streams

---

## Error Codes

| Status Code | Meaning |
|------------|---------|
| 200 | Success |
| 400 | Bad Request (invalid release, missing git_branch) |
| 401/403 | Unauthorized (missing or invalid admin PIN) |
| 404 | Release not found |
| 500 | Internal Server Error (sync failure, Git error) |

---

## Troubleshooting

### Sync Fails with "Git clone failed"

**Check:**
1. `GIT_REPO_URL` is correct
2. SSH key path is valid and readable
3. SSH key has correct permissions (600)
4. Network connectivity to Git server
5. `GIT_SSH_STRICT_HOST_KEY_CHECKING` is set appropriately

### Sync Times Out

**Check:**
1. Repository size (< 5GB recommended)
2. Network bandwidth
3. Increase `GIT_OPERATION_TIMEOUT_SECONDS` if needed

### High Failure Rate Error

**Check:**
1. Test files have valid Python syntax
2. Review failed files in sync log `error_details`
3. Check test file sizes (< 10MB)

### SSE Stream Disconnects

**Check:**
1. Firewall/proxy timeout settings
2. Client timeout configuration
3. Job completed (check sync history)

---

## See Also

- [CLAUDE.md](../CLAUDE.md) - Full application documentation
- [PR26_FIXES_SUMMARY.md](../PR26_FIXES_SUMMARY.md) - Code review fixes
- [Deployment Guide](deployment/PRODUCTION.md) - Production setup
