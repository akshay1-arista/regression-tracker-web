# Performance Testing - Error Clustering

This document provides guidance on testing and optimizing the error clustering feature for production workloads.

## Load Testing Script

The `scripts/load_test_clustering.py` script simulates concurrent users accessing the clustering endpoint to help you assess production server capacity.

### Prerequisites

Ensure `httpx` is installed:
```bash
pip install httpx
```

### Basic Usage

```bash
# Test against local development server
python scripts/load_test_clustering.py

# Test against production server
python scripts/load_test_clustering.py --url https://your-prod-server.com

# Customize load parameters
python scripts/load_test_clustering.py \
  --url http://localhost:8000 \
  --release 7.0.0.0 \
  --module business_policy \
  --job-id 1 \
  --concurrent 10 \
  --iterations 3
```

### Parameters

- `--url`: Base URL of the API server (default: `http://localhost:8000`)
- `--release`: Release name (default: `7.0.0.0`)
- `--module`: Module name (default: `business_policy`)
- `--job-id`: Job ID (default: `1`)
- `--concurrent`: Number of concurrent requests per iteration (default: `10`)
- `--iterations`: Number of test iterations (default: `3`)

### Interpreting Results

The script outputs:
- **Success/Failure Counts**: How many requests completed successfully
- **Response Time Statistics**: Min, max, mean, median, standard deviation
- **Performance Assessment**:
  - P50 (median): Should be < 1 second ✅
  - P95 (95th percentile): Should be < 2 seconds ✅

#### Example Output

```
🔄 Load Testing Error Clustering Endpoint
   URL: http://localhost:8000/api/v1/jobs/7.0.0.0/business_policy/1/failures/clustered
   Concurrent requests: 10
   Iterations: 3
   Total requests: 30

Iteration 1/3...
Iteration 2/3...
Iteration 3/3...

============================================================
📊 LOAD TEST RESULTS
============================================================

✅ Successful Requests: 30/30
❌ Failed Requests: 0/30

⏱️  Response Time Statistics:
   Min:     0.245s
   Max:     0.523s
   Mean:    0.387s
   Median:  0.376s
   Std Dev: 0.068s

🎯 Performance Assessment:
   P50: 0.376s ✅
   P95: 0.498s ✅

✅ PASS: Median response time under 1 second - excellent performance!
```

## Performance Targets

Based on the load testing results, the clustering endpoint should meet these targets for typical production workloads:

| Metric | Target | Notes |
|--------|--------|-------|
| **P50 Response Time** | < 1 second | Median response time for typical requests |
| **P95 Response Time** | < 2 seconds | 95% of requests complete within this time |
| **Success Rate** | > 95% | Minimum acceptable success rate |
| **Failure Threshold** | < 10% | Higher failure rates indicate server overload |

### Failure Scenarios

If the load test shows poor performance:

#### P50 > 1 second (Warning)
- Consider adding caching (see Caching Strategy below)
- Review database query performance
- Check for N+1 query issues

#### P50 > 2 seconds (Critical)
- Caching highly recommended
- Consider reducing clustering scope (limit test results returned)
- Review server resources (CPU, memory)

#### Failure Rate > 10% (Critical)
- Server may be overloaded
- Increase Gunicorn workers
- Add load balancer if necessary
- Consider horizontal scaling

## Caching Strategy

To improve performance for repeated queries, implement Redis caching for the clustering endpoint:

### 1. Install Redis

```bash
# macOS
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis
```

### 2. Update .env Configuration

```bash
# Add to .env file
REDIS_URL=redis://localhost:6379/0
```

### 3. Cache Behavior

The clustering endpoint will automatically use Redis cache when configured:
- **Cache Key**: `error_clusters:{release}:{module}:{job_id}`
- **TTL**: 5 minutes (300 seconds)
- **Invalidation**: Automatic on new data import for same job

### 4. Expected Performance Improvement

With caching enabled:
- **First request (cache miss)**: 200-500ms (clustering computation)
- **Subsequent requests (cache hit)**: 10-20ms (Redis retrieval)
- **Cache hit rate**: Expected > 80% for typical usage

## Production Server Sizing

Based on expected load:

### Small Deployment (1-10 concurrent users)
- **Server**: 2 vCPUs, 4GB RAM
- **Gunicorn Workers**: 4
- **Caching**: Optional (in-memory cache sufficient)
- **Expected P50**: < 500ms without cache, < 50ms with cache

### Medium Deployment (10-50 concurrent users)
- **Server**: 4 vCPUs, 8GB RAM
- **Gunicorn Workers**: 8
- **Caching**: Recommended (Redis)
- **Expected P50**: < 500ms without cache, < 50ms with cache

### Large Deployment (50+ concurrent users)
- **Server**: 8+ vCPUs, 16GB+ RAM
- **Gunicorn Workers**: 16+
- **Caching**: Required (Redis with persistence)
- **Load Balancer**: Recommended for horizontal scaling
- **Expected P50**: < 500ms without cache, < 50ms with cache

## Monitoring Production Performance

### 1. Enable Detailed Logging

In `app/routers/jobs.py`, the clustering endpoint already logs:
- Number of failures processed
- Number of clusters created
- Processing time

Monitor these logs:
```bash
# View clustering-related logs
sudo journalctl -u regression-tracker -f | grep "clustered_failures"
```

### 2. Application Performance Monitoring (Optional)

Consider integrating APM tools:
- **Prometheus + Grafana**: For metrics collection and visualization
- **Sentry**: For error tracking and performance monitoring
- **New Relic/DataDog**: For comprehensive APM

### 3. Key Metrics to Track

- **Response Time Distribution**: P50, P95, P99
- **Request Volume**: Requests per minute/hour
- **Cache Hit Rate**: Percentage of requests served from cache
- **Error Rate**: 4xx/5xx response codes
- **Database Query Time**: Time spent in clustering computation

## Optimization Recommendations

### 1. Database Indexes

Ensure indexes exist on frequently queried columns (already implemented):
```sql
CREATE INDEX idx_job_status ON test_results (job_id, status);
```

### 2. Pagination

The clustering endpoint supports pagination:
```bash
# Fetch first 20 clusters
GET /api/v1/jobs/{release}/{module}/{job_id}/failures/clustered?limit=20&skip=0

# Fetch next 20 clusters
GET /api/v1/jobs/{release}/{module}/{job_id}/failures/clustered?limit=20&skip=20
```

Default limit: 100 clusters (suitable for most use cases)

### 3. Filtering

Use `min_cluster_size` parameter to reduce response size:
```bash
# Only return clusters with 5+ tests
GET /api/v1/jobs/{release}/{module}/{job_id}/failures/clustered?min_cluster_size=5
```

### 4. Background Processing (Future Enhancement)

For very large jobs (500+ failures), consider:
- Pre-computing clusters during data import
- Storing clusters in database
- Incremental clustering updates

## Troubleshooting

### Issue: Load test shows high latency (P50 > 1s)

**Diagnosis Steps:**
1. Check database query performance:
   ```bash
   # Enable SQLAlchemy query logging
   echo "LOG_LEVEL=DEBUG" >> .env
   ```

2. Profile clustering algorithm:
   ```python
   # Add timing logs in error_clustering_service.py
   import time
   start = time.time()
   # ... clustering logic
   logger.info(f"Clustering took {time.time() - start:.3f}s")
   ```

3. Check server resources:
   ```bash
   # CPU usage
   top -p $(pgrep -f gunicorn)

   # Memory usage
   ps aux | grep gunicorn
   ```

**Solutions:**
- Enable Redis caching
- Increase Gunicorn workers
- Optimize database queries
- Add pagination to frontend

### Issue: Load test shows failures (> 10% failure rate)

**Diagnosis Steps:**
1. Check error logs:
   ```bash
   sudo journalctl -u regression-tracker -n 100 | grep ERROR
   ```

2. Check Gunicorn worker health:
   ```bash
   systemctl status regression-tracker
   ```

3. Check database connection pool:
   ```bash
   # Look for "pool limit exceeded" errors
   grep "pool" /var/log/regression-tracker/error.log
   ```

**Solutions:**
- Increase Gunicorn timeout (default: 30s)
- Increase SQLAlchemy pool size
- Add connection pooling for Redis
- Scale horizontally with load balancer

## Benchmarking Different Scenarios

Test various scenarios to understand performance characteristics:

### Scenario 1: Small Job (10-50 failures)
```bash
python scripts/load_test_clustering.py --concurrent 5 --iterations 2
```
Expected: P50 < 200ms

### Scenario 2: Medium Job (50-200 failures)
```bash
python scripts/load_test_clustering.py --concurrent 10 --iterations 3
```
Expected: P50 < 500ms

### Scenario 3: Large Job (200+ failures)
```bash
# Use a job with many failures
python scripts/load_test_clustering.py --job-id <large_job> --concurrent 10 --iterations 3
```
Expected: P50 < 1000ms (cache strongly recommended)

### Scenario 4: High Concurrency (Stress Test)
```bash
python scripts/load_test_clustering.py --concurrent 50 --iterations 1
```
Expected: Success rate > 95%, no server crashes

## Next Steps

After running load tests:

1. **Review Results**: Compare against performance targets
2. **Enable Caching**: If P50 > 500ms, enable Redis caching
3. **Monitor Production**: Set up monitoring and alerts
4. **Iterate**: Re-run tests after optimizations

For questions or issues, consult the main documentation or system logs.
