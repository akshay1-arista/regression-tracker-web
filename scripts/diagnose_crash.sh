#!/bin/bash
# Quick diagnostic script for worker crash investigation
# Usage: ./scripts/diagnose_crash.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_PATH="$PROJECT_ROOT/data/regression_tracker.db"

echo "========================================="
echo "Regression Tracker Crash Diagnostics"
echo "========================================="
echo ""

# 1. Check gunicorn configuration
echo "1. Gunicorn Configuration:"
echo "-------------------------------------------"
if [ -f "$PROJECT_ROOT/gunicorn.conf.py" ]; then
    echo "Current timeout settings:"
    grep -E "^timeout|^graceful_timeout|^workers" "$PROJECT_ROOT/gunicorn.conf.py" || echo "  (using defaults)"
else
    echo "  ⚠ gunicorn.conf.py not found!"
fi
echo ""

# 2. Check system memory
echo "2. System Memory:"
echo "-------------------------------------------"
free -h
echo ""

# 3. Check for OOM killer events
echo "3. OOM Killer Events (last 24 hours):"
echo "-------------------------------------------"
if sudo -n true 2>/dev/null; then
    sudo journalctl -k --since "24 hours ago" | grep -i "out of memory" || echo "  No OOM events found"
else
    echo "  ⚠ Requires sudo to check kernel logs"
    echo "  Run: sudo dmesg -T | grep -i 'out of memory'"
fi
echo ""

# 4. Check worker crashes
echo "4. Recent Worker Crashes:"
echo "-------------------------------------------"
if sudo -n true 2>/dev/null; then
    echo "WORKER TIMEOUT events:"
    sudo journalctl -u regression-tracker --since "7 days ago" | grep "WORKER TIMEOUT" | tail -5 || echo "  None found"
    echo ""
    echo "SIGKILL events:"
    sudo journalctl -u regression-tracker --since "7 days ago" | grep "SIGKILL" | tail -5 || echo "  None found"
else
    echo "  ⚠ Requires sudo to check service logs"
    echo "  Run: sudo journalctl -u regression-tracker --since '7 days ago' | grep -E 'WORKER TIMEOUT|SIGKILL'"
fi
echo ""

# 5. Check database
echo "5. Database Status:"
echo "-------------------------------------------"
if [ -f "$DB_PATH" ]; then
    echo "Database size: $(du -h "$DB_PATH" | cut -f1)"
    echo ""
    echo "Table counts:"
    sqlite3 "$DB_PATH" <<EOF
SELECT
    'Jobs: ' || COUNT(*) FROM jobs
UNION ALL SELECT
    'Test Results: ' || COUNT(*) FROM test_results
UNION ALL SELECT
    'Metadata: ' || COUNT(*) FROM testcase_metadata;
EOF
    echo ""
    echo "Journal mode:"
    sqlite3 "$DB_PATH" "PRAGMA journal_mode;"
    echo ""
    echo "Busy timeout:"
    sqlite3 "$DB_PATH" "PRAGMA busy_timeout;"
else
    echo "  ⚠ Database not found at: $DB_PATH"
fi
echo ""

# 6. Check for large artifacts
echo "6. Large Test Result Files:"
echo "-------------------------------------------"
if [ -d "$PROJECT_ROOT/logs" ]; then
    echo "Top 10 largest test-results.xml files:"
    find "$PROJECT_ROOT/logs" -name "test-results.xml" -type f -exec du -h {} \; 2>/dev/null | \
        sort -rh | head -10 || echo "  No artifacts found"
else
    echo "  No logs directory found"
fi
echo ""

# 7. Check specific job 14
echo "7. Job 14 Details (from crash):"
echo "-------------------------------------------"
if [ -f "$DB_PATH" ]; then
    sqlite3 "$DB_PATH" <<EOF
SELECT
    j.id,
    j.job_name,
    r.version || '/' || m.name as release_module,
    j.total_tests as tests,
    datetime(j.timestamp) as created
FROM jobs j
JOIN modules m ON j.module_id = m.id
JOIN releases r ON m.release_id = r.id
WHERE j.id = 14;
EOF

    # Find artifact for job 14
    echo ""
    echo "Job 14 artifact files:"
    find "$PROJECT_ROOT/logs" -path "*/14/test-results.xml" -exec sh -c '
        echo "  Path: {}"
        echo "  Size: $(du -h {} | cut -f1)"
        echo "  Lines: $(wc -l < {})"
        echo "  Tests: $(grep -c "<testcase" {})"
    ' \; 2>/dev/null || echo "  No artifact found for job 14"
else
    echo "  Database not accessible"
fi
echo ""

# 8. Current gunicorn processes
echo "8. Current Gunicorn Processes:"
echo "-------------------------------------------"
ps aux | grep gunicorn | grep -v grep | awk '{printf "  PID: %s, MEM: %s%%, VSZ: %s KB, CMD: %s\n", $2, $4, $5, $11}' || echo "  No gunicorn processes running"
echo ""

# 9. Recommendations
echo "========================================="
echo "RECOMMENDATIONS:"
echo "========================================="
echo ""

# Check timeout
if [ -f "$PROJECT_ROOT/gunicorn.conf.py" ]; then
    TIMEOUT=$(grep "^timeout" "$PROJECT_ROOT/gunicorn.conf.py" | grep -oE '[0-9]+' || echo "30")
    if [ "$TIMEOUT" -lt 120 ]; then
        echo "⚠ CRITICAL: Worker timeout is ${TIMEOUT}s (too low)"
        echo "   Action: Increase to 300s in gunicorn.conf.py"
        echo "   Add: timeout = 300"
        echo ""
    fi
fi

# Check WAL mode
if [ -f "$DB_PATH" ]; then
    JOURNAL_MODE=$(sqlite3 "$DB_PATH" "PRAGMA journal_mode;" 2>/dev/null)
    if [ "$JOURNAL_MODE" != "wal" ]; then
        echo "⚠ WARNING: SQLite not using WAL mode (current: $JOURNAL_MODE)"
        echo "   Action: Enable WAL mode for better concurrency"
        echo "   Run: sqlite3 $DB_PATH 'PRAGMA journal_mode=WAL;'"
        echo ""
    fi
fi

echo "Next steps:"
echo "1. Review full investigation guide: INVESTIGATION_GUIDE.md"
echo "2. Check detailed crash logs:"
echo "   sudo journalctl -u regression-tracker --since '2026-01-28 04:08:00' --until '2026-01-28 04:14:00'"
echo "3. Test parsing job 14 manually (see INVESTIGATION_GUIDE.md step 3)"
echo "4. Increase worker timeout if < 300s"
echo "5. Enable SQLite WAL mode if not enabled"
echo ""
