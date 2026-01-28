# Worker Crash Investigation Guide

## Incident Summary

**Date**: 2026-01-28 04:10-04:12
**Issue**: Gunicorn worker (PID 23333) killed with SIGKILL during Jenkins artifact import
**Last Operation**: Importing VPN job 14
**Timeline**:
- 04:10:22 - Started importing VPN job 14
- 04:11:54 - Worker timeout detected (92 seconds elapsed)
- 04:12:15 - Worker killed with SIGKILL (21 seconds after timeout)

## Root Cause Hypotheses

1. **Memory Exhaustion** - Worker consumed too much RAM parsing large XML
2. **Worker Timeout** - Operation exceeded configured timeout (default 30s)
3. **Database Lock** - SQLite write lock or long transaction
4. **Large Artifact** - Exceptionally large test-results.xml file
5. **Infinite Loop** - Parser or import logic got stuck

---

## Investigation Steps

### 1. Check System Resources

**Memory Usage During Incident:**
```bash
# Check system memory and swap
free -h
cat /proc/meminfo | grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree'

# Check for OOM killer events around 04:10-04:12
sudo journalctl -k --since "2026-01-28 04:00:00" --until "2026-01-28 04:15:00" | grep -i "out of memory"
sudo dmesg -T | grep -i "out of memory" | tail -20

# Check overall system resource usage
vmstat 1 10
```

**Current Memory Usage:**
```bash
# Check current process memory
ps aux | grep gunicorn | awk '{print $2, $4, $6, $11}' | column -t

# Total memory by gunicorn workers
ps aux | grep gunicorn | awk '{sum+=$6} END {print sum/1024 " MB"}'
```

### 2. Review Gunicorn Configuration

**Check worker timeout settings:**
```bash
# View current gunicorn config
cat gunicorn.conf.py | grep -E 'timeout|workers|worker_class|max_requests'
```

**Expected settings:**
- `timeout = 30` (default) - **TOO LOW for large imports**
- `graceful_timeout = 30` (default)
- `workers = <CPU_COUNT>` (multiple workers)

**Recommended changes:**
```python
# gunicorn.conf.py
timeout = 300          # 5 minutes for large imports
graceful_timeout = 60  # 1 minute for graceful shutdown
max_requests = 1000    # Restart workers periodically
max_requests_jitter = 50
```

### 3. Analyze the Problematic Job

**Identify VPN job 14:**
```bash
# Query database for job details
sqlite3 data/regression_tracker.db <<EOF
SELECT
    j.id,
    j.job_name,
    j.parent_job_id,
    r.version as release,
    m.name as module,
    j.total_tests,
    j.passed,
    j.failed,
    j.error,
    datetime(j.timestamp) as timestamp
FROM jobs j
JOIN modules m ON j.module_id = m.id
JOIN releases r ON m.release_id = r.id
WHERE j.id = 14;
EOF
```

**Check artifact size:**
```bash
# Find the artifact file
find logs/ -name "test-results.xml" -path "*/14/*" -exec ls -lh {} \;

# If found, get detailed stats
find logs/ -name "test-results.xml" -path "*/14/*" -exec sh -c '
  file={}
  echo "File: $file"
  echo "Size: $(du -h "$file" | cut -f1)"
  echo "Lines: $(wc -l < "$file")"
  echo "Test cases: $(grep -c "<testcase" "$file")"
  echo "---"
' \;
```

**Manually test parsing this artifact:**
```bash
# Create test script
cat > test_parse_job14.py <<'SCRIPT'
import sys
import time
import tracemalloc
from app.parser.junit_parser import parse_junit_xml

# Start memory tracking
tracemalloc.start()

# Find artifact path
artifact_path = "logs/*/vpn/14/test-results.xml"  # Adjust path as needed

print(f"Parsing: {artifact_path}")
start_time = time.time()

try:
    results = parse_junit_xml(artifact_path)
    elapsed = time.time() - start_time

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\n✓ Parse successful!")
    print(f"  Duration: {elapsed:.2f}s")
    print(f"  Test results: {len(results)}")
    print(f"  Memory (current): {current / 1024 / 1024:.2f} MB")
    print(f"  Memory (peak): {peak / 1024 / 1024:.2f} MB")

except Exception as e:
    elapsed = time.time() - start_time
    print(f"\n✗ Parse failed after {elapsed:.2f}s")
    print(f"Error: {e}")
    tracemalloc.stop()
    sys.exit(1)
SCRIPT

python test_parse_job14.py
```

### 4. Check Database Lock Issues

**Active connections and locks:**
```bash
# Check for long-running queries or locks
sqlite3 data/regression_tracker.db "PRAGMA busy_timeout;"
sqlite3 data/regression_tracker.db "PRAGMA journal_mode;"

# Enable WAL mode if not already (reduces locks)
sqlite3 data/regression_tracker.db "PRAGMA journal_mode=WAL;"
```

**Database size and fragmentation:**
```bash
# Check database size
ls -lh data/regression_tracker.db*

# Check table sizes
sqlite3 data/regression_tracker.db <<EOF
SELECT
    name,
    (SELECT COUNT(*) FROM test_results) as test_results_count,
    (SELECT COUNT(*) FROM jobs) as jobs_count,
    (SELECT COUNT(*) FROM testcase_metadata) as metadata_count;
.quit
EOF
```

### 5. Review Application Logs

**Full logs around incident time:**
```bash
# Detailed logs with context
sudo journalctl -u regression-tracker \
  --since "2026-01-28 04:08:00" \
  --until "2026-01-28 04:14:00" \
  -o short-iso-precise \
  | tee /tmp/crash_logs.txt

# Look for patterns before crash
grep -E "vpn|job 14|ERROR|WARNING" /tmp/crash_logs.txt
```

**Check for previous similar crashes:**
```bash
# Search for all WORKER TIMEOUT events
sudo journalctl -u regression-tracker --since "7 days ago" | grep "WORKER TIMEOUT"

# Search for SIGKILL events
sudo journalctl -u regression-tracker --since "7 days ago" | grep "SIGKILL"
```

### 6. Test Import with Enhanced Logging

**Enable debug logging temporarily:**
```bash
# Create debug test script
cat > debug_import.py <<'SCRIPT'
import logging
import sys
from app.database import SessionLocal
from app.services.import_service import import_jenkins_job

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

db = SessionLocal()
try:
    # Test import job 14 (adjust release/module as needed)
    release_version = "7.0"  # Replace with actual
    module_name = "vpn"
    build_number = 14

    print(f"Testing import: {release_version}/{module_name}/{build_number}")

    # This will log detailed progress
    result = import_jenkins_job(
        db=db,
        release_version=release_version,
        module_name=module_name,
        build_number=build_number,
        parent_job_id=None,  # Set if child job
        force=True
    )

    print(f"\n✓ Import successful: {result}")

except Exception as e:
    print(f"\n✗ Import failed: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
SCRIPT

# Run with timeout
timeout 120 python debug_import.py
```

---

## Immediate Mitigation

### Option 1: Increase Worker Timeout (Recommended)

Edit [gunicorn.conf.py](gunicorn.conf.py):
```python
timeout = 300  # 5 minutes instead of 30 seconds
```

Restart service:
```bash
sudo systemctl restart regression-tracker
```

### Option 2: Enable Streaming Import (If Available)

If the import service supports streaming/chunked parsing, enable it to reduce memory usage.

### Option 3: Skip Problematic Jobs

Temporarily skip job 14 until investigation complete:
```bash
# Mark job as processed without importing
sqlite3 data/regression_tracker.db <<EOF
INSERT OR IGNORE INTO jobs (
    id, job_name, parent_job_id, module_id,
    timestamp, total_tests, passed, failed, error, skipped
) VALUES (
    14, 'vpn-14-skipped', NULL,
    (SELECT id FROM modules WHERE name='vpn' LIMIT 1),
    datetime('now'), 0, 0, 0, 0, 0
);
EOF
```

---

## Monitoring Going Forward

### 1. Add Memory Tracking

Add to import code (in [app/services/import_service.py](app/services/import_service.py)):
```python
import tracemalloc
import logging

logger = logging.getLogger(__name__)

def import_jenkins_job(...):
    tracemalloc.start()

    try:
        # ... existing import logic ...

        current, peak = tracemalloc.get_traced_memory()
        logger.info(f"Memory usage - Current: {current / 1024 / 1024:.2f}MB, Peak: {peak / 1024 / 1024:.2f}MB")

    finally:
        tracemalloc.stop()
```

### 2. Add Progress Logging

Log progress during large imports:
```python
logger.info(f"Parsing XML: {artifact_path}")
results = parse_junit_xml(artifact_path)
logger.info(f"Parsed {len(results)} test results")

logger.info(f"Starting database insert (batch size: {BATCH_SIZE})")
# ... database operations ...
logger.info(f"Database insert complete")
```

### 3. Monitor System Resources

Set up monitoring alerts:
```bash
# Install monitoring tools if not present
sudo apt-get install sysstat

# Enable resource monitoring
cat > /etc/cron.d/regression-tracker-monitor <<'EOF'
*/5 * * * * root ps aux | grep gunicorn | awk '{sum+=$4} END {if(sum>80) print "High memory: " sum "%"}' >> /var/log/regression-tracker-monitor.log
EOF
```

---

## Expected Findings

Based on the logs, you should find:

1. **Worker timeout = 30s** (too low for large imports)
2. **VPN job 14 artifact is large** (>10MB or >10,000 test cases)
3. **Memory spike during XML parsing** (>500MB per worker)
4. **No database locks** (SQLite should handle this fine with WAL mode)

## Next Steps

1. ✅ Run investigation steps 1-3 above
2. ✅ Increase worker timeout to 300s
3. ✅ Test parsing job 14 artifact manually
4. ✅ Enable WAL mode on SQLite
5. ✅ Add memory tracking logging
6. ✅ Monitor for recurrence

---

## Related Files

- [gunicorn.conf.py](gunicorn.conf.py) - Worker configuration
- [app/services/import_service.py](app/services/import_service.py) - Import logic
- [app/parser/junit_parser.py](app/parser/junit_parser.py) - XML parsing
- [app/routers/jenkins.py](app/routers/jenkins.py) - Download endpoint

## Questions to Answer

- [ ] What is the size of VPN job 14 artifact?
- [ ] What is the current worker timeout setting?
- [ ] Is WAL mode enabled on SQLite?
- [ ] Are there OOM killer events in system logs?
- [ ] Does job 14 import succeed when run manually?
