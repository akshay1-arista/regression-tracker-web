# Redis Migration Guide

This guide explains how to migrate from in-memory job tracking to Redis for multi-worker support.

## Overview

The current implementation uses in-memory dictionaries for job tracking, which doesn't work across multiple Gunicorn workers. Redis provides shared state that all workers can access.

## Changes Required

### 1. Install Redis

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install redis-server
sudo systemctl start redis
sudo systemctl enable redis

# Verify Redis is running
redis-cli ping  # Should respond with "PONG"
```

### 2. Update .env Configuration

Add Redis URL to your `.env` file:

```bash
# Redis Configuration (for multi-worker job tracking)
REDIS_URL=redis://localhost:6379/0
```

### 3. Install Python Dependencies

```bash
cd /opt/regression-tracker-web
source venv/bin/activate
pip install redis>=5.0.0
```

### 4. Pull Latest Code

```bash
cd /opt/regression-tracker-web
sudo git pull origin main
```

### 5. Restart Service

```bash
sudo systemctl restart regression-tracker
```

## How It Works

### Before (In-Memory)
- Each Gunicorn worker has its own `download_jobs` and `log_queues` dictionaries
- Job started in Worker 1 → invisible to Worker 2, 3, etc.
- User refresh might hit different worker → 404 Not Found

### After (Redis)
- All workers share same Redis backend
- Job started in Worker 1 → visible to all workers
- User can refresh/check status from any worker
- Automatic fallback to in-memory if Redis unavailable

## Configuration Options

### Multi-Worker with Redis (Recommended for Production)
```bash
# .env
REDIS_URL=redis://localhost:6379/0
```

```python
# gunicorn.conf.py
workers = multiprocessing.cpu_count() * 2 + 1  # e.g., 9 workers on 4-core
```

### Single Worker without Redis (Development)
```bash
# .env
REDIS_URL=  # Leave empty or omit
```

```python
# gunicorn.conf.py
workers = 1
```

## Testing

### Test Redis Connection
```bash
cd /opt/regression-tracker-web
python3 -c "
from app.utils.job_tracker import get_job_tracker
tracker = get_job_tracker()
print(f'Using Redis: {tracker.use_redis}')
print(f'Backend: {\"Redis\" if tracker.use_redis else \"In-Memory\"}')
"
```

### Test Job Tracking
1. Start a download from the UI
2. Note the job ID
3. Open another browser/tab
4. Check job status → should be visible

## Rollback

To rollback to in-memory (single worker):

1. Set `REDIS_URL=` (empty) in `.env`
2. Set `workers = 1` in `gunicorn.conf.py`
3. Restart: `sudo systemctl restart regression-tracker`

## Monitoring

### Check Redis Usage
```bash
redis-cli info memory
redis-cli keys "job:*"  # List all job keys
redis-cli keys "queue:*"  # List all queue keys
```

### Clear All Jobs (if needed)
```bash
redis-cli FLUSHDB  # Clear current database
```
