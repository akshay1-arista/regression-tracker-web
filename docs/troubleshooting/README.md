# Troubleshooting Guide

This directory contains troubleshooting documentation for common production issues with the Regression Tracker Web application.

## Available Guides

### Worker Crashes

- **[worker-crash-analysis.md](worker-crash-analysis.md)** - Analysis of worker timeout crashes during Jenkins artifact imports
  - Timeline analysis and root cause
  - Immediate fixes (increase timeout configuration)
  - Long-term improvements
  - Verification steps

- **[worker-crash-investigation.md](worker-crash-investigation.md)** - Comprehensive investigation procedures
  - Step-by-step diagnostic procedures
  - System resource checks
  - Database analysis
  - Manual testing procedures
  - Monitoring setup

## Quick Reference

### Common Issues

| Issue | Symptom | Solution | Doc Reference |
|-------|---------|----------|---------------|
| Worker Timeout | `WORKER TIMEOUT` in logs, worker killed with SIGKILL | Increase `GUNICORN_TIMEOUT` to 300s | [worker-crash-analysis.md](worker-crash-analysis.md#immediate-fix) |
| Large Import Fails | Import times out during large VPN/DataPlane jobs | Test manually, check artifact size, increase timeout | [worker-crash-investigation.md](worker-crash-investigation.md#step-3-test-import-manually-5-minutes) |
| Database Locks | SQLite busy errors | Enable WAL mode: `PRAGMA journal_mode=WAL;` | [worker-crash-analysis.md](worker-crash-analysis.md#1-enable-sqlite-wal-mode) |
| Memory Issues | OOM killer events | Check for memory leaks, reduce worker count | [worker-crash-investigation.md](worker-crash-investigation.md#1-check-system-resources) |

### Quick Diagnostic Commands

```bash
# Check worker timeout configuration
grep "^timeout" gunicorn.conf.py

# Check for recent crashes
sudo journalctl -u regression-tracker --since "24 hours ago" | grep -E 'WORKER TIMEOUT|SIGKILL'

# Check system memory
free -h

# Check database mode
sqlite3 data/regression_tracker.db "PRAGMA journal_mode;"

# Run automated diagnostics
./scripts/diagnose_crash.sh
```

### Scripts

Located in `scripts/` directory:

- **[diagnose_crash.sh](../../scripts/diagnose_crash.sh)** - Automated diagnostic script for worker crashes
- **[test_job_import.py](../../scripts/test_job_import.py)** - Manual job import testing with memory tracking

## Getting Help

1. **Review logs**: `sudo journalctl -u regression-tracker -f`
2. **Run diagnostics**: `./scripts/diagnose_crash.sh`
3. **Check guides**: Review relevant troubleshooting document above
4. **Test manually**: Use `scripts/test_job_import.py` for isolated testing

## Related Documentation

- [Production Deployment](../deployment/PRODUCTION.md) - Production setup and configuration
- [Testing Guide](../deployment/TESTING.md) - Testing procedures
- [Security Setup](../guides/security-setup.md) - Security configuration

---

**Last Updated**: 2026-01-28
