# Git-Based Metadata Synchronization Setup Guide

This guide explains how to configure and use the Git-based metadata synchronization feature in Regression Tracker Web.

## Overview

The Git metadata sync feature automatically extracts test metadata from your Git repository by parsing pytest decorators using AST (Abstract Syntax Tree) parsing. This eliminates the need for manual CSV imports and ensures metadata stays in sync with your test code.

## Features

- **Automatic discovery** of test cases from Git repository
- **AST-based parsing** - doesn't execute tests, just reads decorators
- **Release-specific metadata** - different metadata for different releases
- **Scheduled sync** - automatic updates on configurable interval
- **Manual sync** - on-demand sync via Admin UI
- **Failed file tracking** - visibility into parsing errors
- **Retry logic** - automatic retries with exponential backoff

## Prerequisites

### 1. Git Repository Access

You need either:
- **SSH access** (recommended): SSH key with read access to your repository
- **HTTPS access**: Personal access token (less secure, not recommended)

### 2. SSH Key Setup (Recommended)

```bash
# Generate SSH key if you don't have one
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"

# Add public key to GitHub/GitLab
cat ~/.ssh/id_rsa.pub
# Copy and add to GitHub: Settings → SSH Keys → New SSH key

# Test SSH connection
ssh -T git@github.com
# Should see: "Hi username! You've successfully authenticated..."
```

### 3. Repository Structure

Your repository should contain pytest tests with markers:

```python
import pytest

@pytest.mark.testbed(topology='5-site')
@pytest.mark.testmanagement(case=867789, priority='P0')
def test_example():
    """Test example."""
    pass
```

## Configuration

### Step 1: Edit `.env` File

Add the following configuration to your `.env` file:

```bash
# Git Repository Configuration
GIT_REPO_URL=git@github.com:your-org/your-repo.git
GIT_REPO_LOCAL_PATH=./data/git_repos/your_repo
GIT_REPO_BRANCH=master
GIT_REPO_SSH_KEY_PATH=~/.ssh/id_rsa
GIT_SSH_STRICT_HOST_KEY_CHECKING=true

# Test Discovery Paths (relative to repository root)
TEST_DISCOVERY_BASE_PATH=tests
TEST_DISCOVERY_STAGING_CONFIG=config/staging_tests.ini

# Metadata Sync Scheduling
METADATA_SYNC_ENABLED=false  # Set to true to enable scheduled sync
METADATA_SYNC_INTERVAL_HOURS=24.0  # Sync every 24 hours
METADATA_SYNC_ON_STARTUP=false  # Set to true to sync on app startup
```

### Step 2: Configure SSH Key Permissions

Ensure your SSH key has correct permissions:

```bash
chmod 600 ~/.ssh/id_rsa
chmod 644 ~/.ssh/id_rsa.pub
```

**Security Note**: The application will warn if your SSH key has overly permissive permissions (e.g., 644 or 755).

### Step 3: Apply Database Migration

```bash
# Apply the metadata sync tables migration
alembic upgrade head

# Verify migration
alembic current
# Should show: 36c78902bcf4 (includes index on release_id)
```

### Step 4: Configure Release Git Branches

Each release can have its own Git branch for release-specific metadata:

```bash
# Via API or database
UPDATE releases SET git_branch = 'master' WHERE name = '7.0';
UPDATE releases SET git_branch = 'release/6.4' WHERE name = '6.4';
```

**Note**: If `releases.git_branch` is NULL, the release will be skipped during sync.

## Usage

### Manual Sync via Admin UI

1. Navigate to http://localhost:8000/admin
2. Enter admin PIN
3. Scroll to "Metadata Sync (Git)" section
4. Select a release or click "Sync All Releases"
5. Click **"Sync Now"** button
6. Monitor real-time progress in the log viewer

### Manual Sync via API

```bash
# Sync specific release
curl -X POST http://localhost:8000/api/v1/admin/metadata-sync/trigger/1 \
  -H "X-Admin-PIN: your_pin"

# Sync all active releases
curl -X POST http://localhost:8000/api/v1/admin/metadata-sync/trigger \
  -H "X-Admin-PIN: your_pin"

# Check sync status
curl http://localhost:8000/api/v1/admin/metadata-sync/status \
  -H "X-Admin-PIN: your_pin"

# View sync history
curl http://localhost:8000/api/v1/admin/metadata-sync/history \
  -H "X-Admin-PIN: your_pin"
```

### Enabling Scheduled Sync

```bash
# Edit .env
METADATA_SYNC_ENABLED=true
METADATA_SYNC_INTERVAL_HOURS=24.0

# Restart application
./start_production.sh
# OR
sudo systemctl restart regression-tracker
```

## Metadata Extraction

### Supported Pytest Markers

#### 1. `@pytest.mark.testbed(topology='...')`

Extracts topology metadata:

```python
@pytest.mark.testbed(topology='5-site')
@pytest.mark.testbed(topology='3-site-ipv6')
@pytest.mark.testbed(topology='5-site-mpg')
```

#### 2. `@pytest.mark.testmanagement(...)`

Extracts test management metadata:

```python
@pytest.mark.testmanagement(
    case=867789,          # TestRail case ID (stored as C867789)
    qtest_tc_id='TC123',  # Alternative test case ID
    priority='P0'         # Test priority
)
```

**Supported priority values**: P0, P1, P2, P3, HIGH, MEDIUM, UNKNOWN

#### 3. Staging vs Production

Tests are classified as STAGING or PROD based on `dp_staging.ini` file:

```ini
# dp_staging.ini
[tests]
test_example_staging = staging
```

- If test is listed in `dp_staging.ini`: `test_state = "STAGING"`
- Otherwise: `test_state = "PROD"`

### Metadata Fields Extracted

| Field | Source | Example |
|-------|--------|---------|
| `testcase_name` | Function/class name | `test_bgp_routing` |
| `test_class_name` | Class name (if any) | `TestBGP` |
| `module` | Directory structure | `routing` |
| `topology` | `@pytest.mark.testbed` | `5-site` |
| `test_state` | `dp_staging.ini` | `PROD` or `STAGING` |
| `test_case_id` | `@pytest.mark.testmanagement(qtest_tc_id)` | `TC123` |
| `testrail_id` | `@pytest.mark.testmanagement(case)` | `C867789` |
| `priority` | `@pytest.mark.testmanagement(priority)` | `P0` |
| `test_path` | Full file path | `tests/routing/test_bgp.py` |

## Global vs Release-Specific Metadata

The system uses a **hybrid storage model**:

### Global Metadata (Baseline)
- Stored with `release_id = NULL`
- Applies to all releases unless overridden
- ~99.9% of tests use Global metadata

### Release-Specific Metadata (Overrides)
- Stored with `release_id = <specific release>`
- Only created when metadata **differs** from Global
- ~0.1% of tests have release-specific metadata

### Example

```
test_example:
  Global (release_id = NULL):
    Priority: P1
    Topology: 5-site

  7.0 (release_id = 2):
    Priority: P0  ← DIFFERS from Global
    Topology: 5-site  ← Same as Global
```

In the UI, this test will show:
- **Global tab**: Priority=P1 (baseline)
- **7.0 tab**: Priority=P0 ⚠️ (warning = differs)

## Monitoring & Troubleshooting

### View Sync Logs

```bash
# Via Admin UI
# Navigate to: Admin → Metadata Sync → View History

# Via database
sqlite3 data/regression_tracker.db
SELECT * FROM metadata_sync_logs ORDER BY started_at DESC LIMIT 10;
```

### Check Failed Files

```bash
# Via API
curl http://localhost:8000/api/v1/admin/metadata-sync/history \
  -H "X-Admin-PIN: your_pin" | jq '.[0].error_details'

# Sample output
{
  "failed_files": [
    "tests/broken_syntax.py",
    "tests/missing_decorator.py"
  ],
  "failed_file_count": 2
}
```

### Common Issues

#### 1. SSH Authentication Failed

**Error**: `Permission denied (publickey)`

**Solution**:
```bash
# Verify SSH key is added to GitHub/GitLab
ssh -T git@github.com

# Check SSH key permissions
ls -la ~/.ssh/id_rsa  # Should be -rw------- (600)

# Test with verbose output
GIT_SSH_COMMAND="ssh -v" git clone git@github.com:org/repo.git /tmp/test
```

#### 2. High File Failure Rate

**Error**: `Test discovery failure rate too high: 15.0% (150/1000 files failed)`

**Causes**:
- Syntax errors in test files
- Missing pytest imports
- Invalid decorator syntax

**Solution**:
```bash
# Review failed files in error_details
# Fix syntax errors in failing files
# Re-run sync

# Adjust threshold if needed (in .env)
METADATA_SYNC_MAX_FILE_FAILURE_RATE=0.20  # Allow 20% failures
METADATA_SYNC_MIN_FILE_FAILURES_TO_ABORT=10
```

#### 3. Repository Not Found

**Error**: `Repository not found or access denied`

**Solution**:
```bash
# Verify repository URL
git ls-remote git@github.com:org/repo.git

# Check SSH key has read access to repository
```

#### 4. Sync Takes Too Long

**Observation**: Sync takes > 10 minutes

**Optimizations**:
```bash
# Use shallow clone (default depth=50)
# Reduce number of test files by configuring TEST_DISCOVERY_BASE_PATH

# Check repository size
du -sh ./data/git_repos/your_repo

# Consider:
# - Excluding large binary files (.gitattributes)
# - Using sparse checkout for test directory only
```

## Advanced Configuration

### Failure Thresholds

Control when sync aborts due to failures:

```bash
# .env file
# File-level thresholds
METADATA_SYNC_MAX_FILE_FAILURE_RATE=0.10  # 10% max file failures
METADATA_SYNC_MIN_FILE_FAILURES_TO_ABORT=5  # Need >5 failures to abort

# Batch-level thresholds (database operations)
METADATA_SYNC_MAX_BATCH_FAILURE_RATE=0.10  # 10% max batch failures
METADATA_SYNC_MIN_BATCH_FAILURES_TO_ABORT=2  # Need >2 batch failures to abort
```

### Retry Configuration

Control retry behavior for transient failures:

```python
# In app/tasks/metadata_sync_poller.py
MAX_RETRIES = 3  # Number of retry attempts
INITIAL_RETRY_DELAY_SECONDS = 60  # Initial delay (1 minute)
RETRY_BACKOFF_MULTIPLIER = 2  # Exponential backoff (1min, 2min, 4min)
```

### Git Operation Timeouts

```python
# In app/services/git_metadata_sync_service.py
GIT_OPERATION_TIMEOUT_SECONDS = 300  # 5 minutes
MAX_REPO_SIZE_MB = 5000  # 5GB max repository size
```

## Performance Considerations

### Sync Performance

Typical sync times for a repository with 10,000 tests:

- **Initial clone**: 2-5 minutes (depends on repo size)
- **Subsequent pulls**: 10-30 seconds
- **AST parsing**: 1-2 minutes
- **Database updates**: 30-60 seconds
- **Total**: 3-7 minutes (first sync), 2-3 minutes (subsequent syncs)

### Optimization Tips

1. **Use SSH keys** - Faster than HTTPS tokens
2. **Limit test discovery path** - Set `TEST_DISCOVERY_BASE_PATH` to specific directory
3. **Schedule during off-hours** - Run sync when system is less busy
4. **Monitor failed files** - Fix syntax errors to improve parse rate

## Security Best Practices

1. **Use SSH keys** - More secure than HTTPS tokens
2. **Restrict key permissions** - chmod 600 on SSH private key
3. **Enable StrictHostKeyChecking** - Prevents MITM attacks
4. **Read-only access** - Git repository only needs read permission
5. **Protect admin PIN** - Use strong admin PIN hash
6. **Audit sync logs** - Monitor who triggers manual syncs

## Next Steps

1. ✅ Configure Git repository access
2. ✅ Apply database migrations
3. ✅ Test manual sync via Admin UI
4. ✅ Verify metadata in database
5. ✅ Enable scheduled sync (optional)
6. ✅ Monitor sync logs regularly

## Support

For issues or questions:
- Check application logs: `sudo journalctl -u regression-tracker -f`
- Review sync logs in Admin UI
- Consult CLAUDE.md for technical details
- Check GitHub Issues for known problems
