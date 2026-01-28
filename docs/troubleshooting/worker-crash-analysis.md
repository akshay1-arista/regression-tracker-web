# Worker Crash Analysis - 2026-01-28

## Executive Summary

**Root Cause**: Worker timeout while importing large VPN job 14 artifact. The import operation took longer than the configured 120-second timeout, causing Gunicorn to kill the worker.

**Impact**: Download operation failed, worker restarted, no data loss but job not imported.

**Solution**: Increase worker timeout to 300 seconds (5 minutes) to handle large artifacts.

---

## Timeline Analysis

| Time | Event | Elapsed |
|------|-------|---------|
| 04:10:22 | Started importing VPN job 14 | 0s |
| 04:11:54 | Worker timeout detected | 92s |
| 04:12:15 | Worker killed with SIGKILL | 113s total |

**Key Observation**: The import was still running at 92 seconds when timeout occurred. The worker didn't respond to SIGTERM for graceful shutdown, so it was forcefully killed with SIGKILL after 21 more seconds.

---

## Current Configuration Issues

### 1. Worker Timeout Too Low

**Current**: `timeout = 120` seconds ([gunicorn.conf.py:20](../../gunicorn.conf.py#L20))

**Problem**: Large test artifacts can take >2 minutes to:
- Download from Jenkins (if not cached)
- Parse XML (10,000+ test cases)
- Insert into database (bulk operations)

**Evidence**: Worker was still actively processing at 92 seconds, hadn't completed by 120 seconds.

### 2. Graceful Timeout

**Current**: `graceful_timeout = 30` seconds ([gunicorn.conf.py:21](../../gunicorn.conf.py#L21))

**Problem**: When worker exceeded timeout, it had 30 seconds to shut down gracefully. It didn't respond (likely blocked in database operation), so SIGKILL was sent.

---

## Investigation Steps to Run on Production Server

### Step 1: Quick Diagnostics (5 minutes)

Run the automated diagnostic script:

```bash
cd /path/to/regression-tracker-web
./scripts/diagnose_crash.sh
```

This will check:
- Current gunicorn settings
- System memory status
- OOM killer events
- Recent crashes
- Database status
- Large artifact files
- Job 14 details

### Step 2: Identify the Problematic Artifact (2 minutes)

Find job 14 artifact and check its size:

```bash
# Search for job 14 artifact
find logs/ -path "*/14/test-results.xml" -exec ls -lh {} \;

# Get detailed stats
find logs/ -path "*/14/test-results.xml" -exec sh -c '
  echo "File: {}"
  echo "Size: $(du -h {} | cut -f1)"
  echo "Lines: $(wc -l < {})"
  echo "Test cases: $(grep -c "<testcase" {})"
' \;
```

**Expected finding**: Large artifact (>10MB or >10,000 test cases)

### Step 3: Test Import Manually (5 minutes)

Test the import in isolation to measure actual time/memory:

```bash
# Determine release and module for job 14
sqlite3 data/regression_tracker.db <<EOF
SELECT r.version, m.name
FROM jobs j
JOIN modules m ON j.module_id = m.id
JOIN releases r ON m.release_id = r.id
WHERE j.id = 14;
EOF

# Test import (replace 7.0 and vpn with actual values)
python scripts/test_job_import.py 7.0 vpn 14
```

This will show:
- Actual time to parse XML
- Actual time to import to database
- Peak memory usage
- Whether it succeeds at all

### Step 4: Check System Resources (2 minutes)

Verify no memory issues:

```bash
# Check current memory
free -h

# Check for OOM killer events around crash time
sudo journalctl -k --since "2026-01-28 04:00:00" --until "2026-01-28 04:15:00" | grep -i "out of memory"

# Check gunicorn memory usage
ps aux | grep gunicorn | awk '{print $2, $4, $6, $11}' | column -t
```

### Step 5: Review Full Crash Logs (2 minutes)

Get detailed context around the crash:

```bash
sudo journalctl -u regression-tracker \
  --since "2026-01-28 04:08:00" \
  --until "2026-01-28 04:14:00" \
  -o short-iso-precise
```

---

## Immediate Fix (5 minutes)

### Option 1: Increase Timeout (Recommended)

Edit [gunicorn.conf.py](gunicorn.conf.py):

```python
# OLD (line 20):
timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))

# NEW:
timeout = int(os.getenv('GUNICORN_TIMEOUT', '300'))  # 5 minutes for large imports
```

**Or** set environment variable without code change:

```bash
# Add to .env or systemd service file
GUNICORN_TIMEOUT=300
```

Then restart:

```bash
sudo systemctl restart regression-tracker
```

### Option 2: Set via Environment Variable (Faster, No Code Edit)

Edit systemd service file:

```bash
sudo systemctl edit regression-tracker
```

Add:

```ini
[Service]
Environment="GUNICORN_TIMEOUT=300"
```

Save and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart regression-tracker
```

Verify:

```bash
# Check if environment variable is set
sudo systemctl show regression-tracker | grep GUNICORN_TIMEOUT

# Monitor logs to confirm new timeout
sudo journalctl -u regression-tracker -f
```

---

## Long-Term Improvements

### 1. Enable SQLite WAL Mode

Reduces database lock contention:

```bash
sqlite3 data/regression_tracker.db "PRAGMA journal_mode=WAL;"
```

This persists across restarts and improves concurrent access.

### 2. Add Memory Tracking to Import Service

Add to [app/services/import_service.py](../../app/services/import_service.py):

```python
import tracemalloc

def import_jenkins_job(...):
    tracemalloc.start()
    start_time = time.time()

    try:
        # ... existing import logic ...

        current, peak = tracemalloc.get_traced_memory()
        duration = time.time() - start_time

        logger.info(
            f"Import complete - Duration: {duration:.2f}s, "
            f"Memory: {peak / 1024 / 1024:.2f}MB peak"
        )

    finally:
        tracemalloc.stop()
```

### 3. Add Progress Logging

Log checkpoints during import:

```python
logger.info(f"[{job_id}] Step 1: Parsing XML...")
results = parse_junit_xml(artifact_path)
logger.info(f"[{job_id}] Step 1 complete: {len(results)} tests")

logger.info(f"[{job_id}] Step 2: Database insert...")
# ... insert logic ...
logger.info(f"[{job_id}] Step 2 complete")
```

This helps identify which step is slow.

### 4. Implement Streaming/Chunked Import

For extremely large artifacts (>50MB), consider:
- Streaming XML parsing (SAX instead of DOM)
- Batch database inserts (already implemented?)
- Progress callbacks for long operations

### 5. Add Health Monitoring

Monitor worker health:

```bash
# Add to cron (every 5 minutes)
*/5 * * * * ps aux | grep gunicorn | awk '{sum+=$4} END {if(sum>80) print strftime("\%Y-\%m-\%d \%H:\%M:\%S") " WARNING: High memory: " sum "%"}'  >> /var/log/regression-tracker-monitor.log
```

---

## Expected Outcomes

After increasing timeout to 300s:

1. ✅ Job 14 imports successfully (if it takes <5 minutes)
2. ✅ No more worker timeouts for typical large jobs
3. ✅ Worker remains responsive during long operations
4. ⚠️ Still need to monitor for jobs >5 minutes (very rare)

---

## Verification Steps

After applying the fix:

1. **Verify configuration change**:
   ```bash
   # Check environment variable
   echo $GUNICORN_TIMEOUT  # Should show 300

   # Or check in running process
   sudo systemctl show regression-tracker | grep GUNICORN_TIMEOUT
   ```

2. **Test manual download**:
   - Navigate to http://your-server:8000/
   - Click "Download Latest" or select specific release/module
   - Monitor logs: `sudo journalctl -u regression-tracker -f`
   - Verify import completes without timeout

3. **Monitor for recurrence**:
   ```bash
   # Check for timeouts in next 7 days
   sudo journalctl -u regression-tracker --since "now" | grep "WORKER TIMEOUT"
   ```

---

## Questions Answered

| Question | Answer |
|----------|--------|
| What caused the crash? | Worker timeout (120s) exceeded during large VPN job import |
| Was it memory (OOM)? | Likely not - SIGKILL was sent by Gunicorn, not kernel OOM killer |
| Why SIGKILL? | Worker didn't respond to graceful shutdown (SIGTERM) within 30s |
| Will it happen again? | Yes, until timeout is increased or job is skipped |
| How to prevent? | Increase timeout to 300s |

---

## Files Changed

To implement the fix:

1. **Option A - Code change**:
   - [gunicorn.conf.py](../../gunicorn.conf.py#L20) - Change `timeout` default from 120 to 300

2. **Option B - Environment variable** (no code change needed):
   - `.env` - Add `GUNICORN_TIMEOUT=300`
   - Or systemd override - Add `Environment="GUNICORN_TIMEOUT=300"`

---

## Additional Resources

- [worker-crash-investigation.md](worker-crash-investigation.md) - Detailed investigation procedures
- [scripts/diagnose_crash.sh](../../scripts/diagnose_crash.sh) - Automated diagnostics
- [scripts/test_job_import.py](../../scripts/test_job_import.py) - Manual import testing

---

## Next Actions

**Immediate (now)**:
1. ✅ Run diagnostic script: `./scripts/diagnose_crash.sh`
2. ✅ Increase timeout to 300s (via env var or code)
3. ✅ Restart service: `sudo systemctl restart regression-tracker`
4. ✅ Test manual download to verify fix

**Short-term (this week)**:
1. Enable SQLite WAL mode
2. Add memory tracking to import service
3. Test importing job 14 manually

**Long-term (next sprint)**:
1. Add progress logging throughout import
2. Implement health monitoring
3. Consider streaming parser for >50MB files
