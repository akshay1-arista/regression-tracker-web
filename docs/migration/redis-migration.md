# Redis Migration for Multi-Worker Support

## Problem

The current implementation uses in-memory dictionaries (`download_jobs` and `log_queues`) which don't work across multiple Gunicorn workers:

```python
# app/routers/jenkins.py
download_jobs: Dict[str, Dict] = {}  # ❌ Per-worker, not shared
log_queues: Dict[str, Queue] = {}    # ❌ Per-worker, not shared
```

**Impact:**
- User A starts download → Request hits Worker 1 → Job stored in Worker 1's memory
- User A checks status → Request hits Worker 2 → Job not found (404)
- Multiple concurrent users get inconsistent results

## Solution

Use Redis as a shared job tracker that all workers can access.

## Implementation Steps

### Step 1: Install and Configure Redis

```bash
# Install Redis
sudo apt update
sudo apt install redis-server

# Start and enable Redis
sudo systemctl start redis
sudo systemctl enable redis

# Test Redis
redis-cli ping  # Should return "PONG"
```

### Step 2: Update Configuration

Add to `/opt/regression-tracker-web/.env`:
```bash
# Redis for multi-worker job tracking
REDIS_URL=redis://localhost:6379/0
```

### Step 3: Install Dependencies

```bash
cd /opt/regression-tracker-web
source venv/bin/activate
pip install redis>=5.0.0
```

### Step 4: Update Code

The job tracker utility (`app/utils/job_tracker.py`) is already implemented and provides:

- **Redis backend** when `REDIS_URL` is configured
- **Automatic fallback** to in-memory if Redis unavailable
- **Transparent API** - same interface regardless of backend

### Step 5: Update Jenkins Router

**Replace in-memory dictionaries with job tracker calls:**

#### Before:
```python
# In-memory storage
download_jobs: Dict[str, Dict] = {}
log_queues: Dict[str, Queue] = {}

# Usage
download_jobs[job_id] = {'status': 'running'}
log_queues[job_id].put(message)
```

#### After:
```python
# Use job tracker
from app.utils.job_tracker import get_job_tracker

# Usage
tracker = get_job_tracker()
tracker.set_job(job_id, {'status': 'running'})
tracker.push_log(job_id, message)
```

### Detailed Code Changes

#### 1. Update imports and globals:

```python
# Remove
download_jobs: Dict[str, Dict] = {}
log_queues: Dict[str, Queue] = {}

# Add
from app.utils.job_tracker import get_job_tracker
```

#### 2. Update trigger_download():

```python
@router.post("/download")
async def trigger_download(...):
    job_id = str(uuid.uuid4())

    # OLD:
    # log_queues[job_id] = Queue()
    # download_jobs[job_id] = {...}

    # NEW:
    tracker = get_job_tracker()
    tracker.set_job(job_id, {
        'id': job_id,
        'release': request.release,
        'status': 'pending',
        'started_at': datetime.utcnow().isoformat(),
        'completed_at': None,
        'error': None
    })
```

#### 3. Update stream_download_logs():

```python
async def stream_download_logs(job_id: str):
    tracker = get_job_tracker()

    # OLD:
    # if job_id not in download_jobs:
    #     raise HTTPException(404)

    # NEW:
    if not tracker.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        while True:
            job = tracker.get_job(job_id)
            if not job:
                break

            # OLD:
            # log_message = log_queues[job_id].get(timeout=0.5)

            # NEW:
            log_message = tracker.pop_log(job_id, timeout=0.5)

            if log_message:
                yield f"data: {json.dumps({'message': log_message})}\n\n"

            if job['status'] in ['completed', 'failed']:
                yield f"data: {json.dumps({'status': job['status']})}\n\n"
                break
```

#### 4. Update get_download_status():

```python
@router.get("/download/{job_id}/status")
async def get_download_status(job_id: str):
    tracker = get_job_tracker()

    # OLD:
    # if job_id not in download_jobs:
    #     raise HTTPException(404)
    # return download_jobs[job_id]

    # NEW:
    job = tracker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
```

#### 5. Update background task functions:

```python
def run_download(job_id, ...):
    tracker = get_job_tracker()

    def log_callback(message: str):
        # OLD:
        # if job_id in log_queues:
        #     log_queues[job_id].put(message)

        # NEW:
        tracker.push_log(job_id, message)
        logger.info(f"[{job_id}] {message}")

    try:
        log_callback("Starting download...")

        # OLD:
        # download_jobs[job_id]['status'] = 'running'

        # NEW:
        job = tracker.get_job(job_id)
        job['status'] = 'running'
        tracker.set_job(job_id, job)

        # ... download logic ...

        # OLD:
        # download_jobs[job_id]['status'] = 'completed'

        # NEW:
        job = tracker.get_job(job_id)
        job['status'] = 'completed'
        job['completed_at'] = datetime.utcnow().isoformat()
        tracker.set_job(job_id, job)

    except Exception as e:
        # OLD:
        # download_jobs[job_id]['status'] = 'failed'

        # NEW:
        job = tracker.get_job(job_id) or {}
        job['status'] = 'failed'
        job['error'] = str(e)
        tracker.set_job(job_id, job)
```

### Step 6: Deploy

```bash
cd /opt/regression-tracker-web
sudo git pull origin main
sudo systemctl restart regression-tracker
```

### Step 7: Verify

```bash
# Check Redis connection
python3 -c "
from app.utils.job_tracker import get_job_tracker
tracker = get_job_tracker()
print(f'Using Redis: {tracker.use_redis}')
"
```

## Testing

### Test 1: Start Download
1. Open browser, start a download
2. Note the job ID from network inspector

### Test 2: Check from Different "Worker"
1. Open incognito/different browser
2. Navigate to status endpoint: `/api/v1/jenkins/download/{job_id}/status`
3. Should see job status (not 404)

### Test 3: Monitor Redis
```bash
# Watch Redis activity
redis-cli monitor

# List active jobs
redis-cli keys "job:*"

# Get job details
redis-cli get "job:your-job-id-here"
```

## Fallback Behavior

If Redis is unavailable, the job tracker automatically falls back to in-memory storage:

```python
# JobTracker initialization
try:
    self.redis_client = redis.from_url(redis_url)
    self.use_redis = True
    logger.info("Using Redis backend")
except:
    self.use_redis = False
    logger.warning("Redis unavailable, using in-memory fallback")
```

This means:
- ✅ Application still works
- ⚠️ Multi-worker issues return (but app doesn't crash)
- 📝 Warning logged for debugging

## Performance

### Redis Overhead
- **Set job**: ~1ms
- **Get job**: ~1ms
- **Push log**: ~0.5ms
- **Pop log**: ~0.5ms (blocking)

### Memory Usage
- Each job: ~1-2 KB in Redis
- TTL: 24 hours (auto-cleanup)
- Log queues: 1 hour TTL

## Monitoring

### Redis Memory
```bash
redis-cli info memory
```

### Active Jobs
```bash
redis-cli --scan --pattern "job:*" | wc -l
```

### Clear Old Jobs (Manual)
```bash
redis-cli KEYS "job:*" | xargs redis-cli DEL
redis-cli KEYS "queue:*" | xargs redis-cli DEL
```

## Troubleshooting

### "Connection refused" Error
```bash
# Check if Redis is running
sudo systemctl status redis

# Start Redis
sudo systemctl start redis
```

### Jobs Not Persisting
```bash
# Check Redis URL in .env
cat /opt/regression-tracker-web/.env | grep REDIS_URL

# Test connection
redis-cli -u redis://localhost:6379/0 ping
```

### High Memory Usage
```bash
# Check Redis memory
redis-cli info memory

# Clear old jobs
redis-cli FLUSHDB
```
