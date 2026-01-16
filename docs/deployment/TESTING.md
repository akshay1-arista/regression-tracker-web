# Testing Guide - Phase 5

This guide covers testing procedures for Phase 5 deployment and validation.

## Table of Contents

- [Data Validation](#data-validation)
- [Performance Testing](#performance-testing)
- [Parallel Operation with CLI](#parallel-operation-with-cli)
- [Production Readiness Checklist](#production-readiness-checklist)

## Data Validation

### Automated Validation Script

The data validation script checks database integrity and calculation accuracy.

```bash
# Run validation with verbose output
python scripts/validate_data.py --verbose

# Export validation report to JSON
python scripts/validate_data.py --export-report reports/validation_$(date +%Y%m%d).json
```

### Validation Tests

The script performs the following checks:

1. **Data Integrity**
   - Orphaned modules (modules without releases)
   - Orphaned jobs (jobs without modules)
   - Orphaned builds (builds without jobs)
   - Orphaned test results (results without builds)
   - Duplicate releases
   - Invalid build numbers

2. **Calculation Accuracy**
   - Total test counts
   - Passed test counts
   - Failed test counts
   - Skipped test counts
   - Pass rate percentages

3. **Data Consistency**
   - Parent-child job relationships
   - Timestamp validity
   - Test result uniqueness within builds

### Manual Validation

Compare web application data with existing CLI tool:

```bash
# Export data from web application
curl http://localhost:8000/api/releases > web_releases.json
curl http://localhost:8000/api/jobs/123 > web_job_123.json

# Compare with CLI tool output
# ... run CLI tool commands ...

# Use diff or jq to compare
jq -S . web_releases.json > web_sorted.json
jq -S . cli_releases.json > cli_sorted.json
diff web_sorted.json cli_sorted.json
```

### Validation Acceptance Criteria

- ✅ Zero orphaned records
- ✅ All calculations match expected values
- ✅ No data inconsistencies
- ✅ Results match CLI tool output (within acceptable variance)

## Performance Testing

### Running Performance Tests

```bash
# Run all performance tests
./scripts/run_performance_tests.sh

# Run specific test categories
pytest tests/test_performance.py::test_homepage_response_time -v
pytest tests/test_performance.py::test_concurrent_requests -v
pytest tests/test_performance.py::test_throughput -v

# Run with detailed output
pytest tests/test_performance.py -v -s
```

### Performance Metrics

The test suite measures:

1. **Response Times**
   - Homepage: < 500ms average
   - API endpoints: < 500ms average
   - List endpoints: < 1000ms average
   - 95th percentile: < 750ms
   - 99th percentile: < 1500ms

2. **Throughput**
   - Target: ≥ 20 requests/second
   - Measured over 100 requests
   - Reports actual throughput achieved

3. **Concurrent Load**
   - 10 concurrent requests
   - All requests succeed (200 OK)
   - Average response time < 2000ms
   - 95th percentile < 3000ms

4. **Database Performance**
   - Query times < 100ms average
   - Tests common query patterns
   - Measures query performance

5. **Memory Stability**
   - Memory leak detection
   - 100 repeated operations
   - Memory growth < 10MB allowed

### Load Testing with Apache Bench

```bash
# Install Apache Bench
# Ubuntu/Debian: sudo apt-get install apache2-utils
# macOS: brew install httpd

# Test with 1000 requests, 10 concurrent
ab -n 1000 -c 10 http://localhost:8000/

# Test specific endpoint
ab -n 500 -c 5 http://localhost:8000/api/releases

# Test with keep-alive
ab -n 1000 -c 10 -k http://localhost:8000/
```

### Load Testing with wrk

```bash
# Install wrk
# Ubuntu: sudo apt-get install wrk
# macOS: brew install wrk

# Run 30-second test with 10 connections
wrk -t10 -c10 -d30s http://localhost:8000/

# Test specific endpoint with script
wrk -t10 -c100 -d60s --latency http://localhost:8000/api/releases
```

### Performance Acceptance Criteria

- ✅ Average response time < 500ms for standard endpoints
- ✅ Throughput ≥ 20 req/s
- ✅ Successfully handles 10+ concurrent requests
- ✅ No memory leaks detected
- ✅ Database queries < 100ms average

## Parallel Operation with CLI

### Testing Simultaneous Access

The web application should operate in parallel with the existing CLI tool.

#### Setup Test Environment

```bash
# Terminal 1: Run web application
./start_production.sh

# Terminal 2: Run CLI tool
# ... run your existing CLI tool ...

# Terminal 3: Monitor both
watch -n 2 'curl -s http://localhost:8000/health/detailed | jq'
```

#### Concurrent Write Test

```bash
# Import data via CLI while web app is running
# CLI tool should import test results
# Web app should poll Jenkins simultaneously

# Verify both systems see the same data
# Check database for consistency
python scripts/validate_data.py
```

#### Database Locking Test

SQLite handles concurrent access with locking. Test scenarios:

1. **Read-Read**: Multiple processes reading simultaneously
   ```bash
   # Terminal 1
   curl http://localhost:8000/api/releases

   # Terminal 2 (simultaneously)
   # CLI tool: query releases
   ```

2. **Read-Write**: One process reading while another writes
   ```bash
   # Terminal 1
   curl http://localhost:8000/api/jobs

   # Terminal 2 (simultaneously)
   # CLI tool: import new test results
   ```

3. **Write-Write**: Multiple processes writing
   ```bash
   # Terminal 1
   curl -X POST http://localhost:8000/api/jenkins/download/123

   # Terminal 2 (simultaneously)
   # CLI tool: import test results
   ```

#### Acceptance Criteria

- ✅ Both systems can read data simultaneously
- ✅ Writes are properly queued/locked
- ✅ No data corruption occurs
- ✅ No deadlocks or timeout errors
- ✅ Data remains consistent across both systems

### Migration from CLI to Web App

If migrating from CLI to web app:

1. **Import Historical Data**
   ```bash
   python scripts/import_existing_data.py
   ```

2. **Run Parallel for Testing Period**
   - Run both systems for 1-2 weeks
   - Compare outputs daily
   - Validate data consistency

3. **Gradual Cutover**
   - Phase 1: Web app read-only, CLI continues writes
   - Phase 2: Web app handles polling, CLI on-demand only
   - Phase 3: Full cutover to web app

4. **Decommission CLI**
   - Verify all functionality migrated
   - Archive CLI tool and documentation
   - Update team processes

## Production Readiness Checklist

### Pre-Deployment

- [ ] All environment variables configured
- [ ] Database migrations applied
- [ ] Admin PIN hash generated and set
- [ ] Jenkins credentials tested
- [ ] SSL/HTTPS certificates configured (if applicable)
- [ ] Firewall rules configured
- [ ] Backup strategy implemented

### Testing

- [ ] Data validation tests passed
- [ ] Performance tests passed
- [ ] Health check endpoints responding
- [ ] API documentation accessible
- [ ] Manual testing completed
- [ ] Concurrent access tested
- [ ] Load testing completed

### Monitoring

- [ ] Health check monitoring configured
- [ ] Log aggregation set up
- [ ] Error alerting configured
- [ ] Performance monitoring enabled
- [ ] Backup verification working

### Documentation

- [ ] Deployment procedures documented
- [ ] Monitoring procedures documented
- [ ] Troubleshooting guide available
- [ ] Rollback procedures tested
- [ ] Team trained on new system

### Security

- [ ] API keys configured (if enabled)
- [ ] Admin authentication tested
- [ ] Rate limiting enabled
- [ ] CORS properly configured
- [ ] Input validation verified
- [ ] Security headers configured
- [ ] Vulnerability scan completed

### Performance

- [ ] Worker count optimized
- [ ] Database indexes created
- [ ] Caching enabled and tested
- [ ] Resource limits configured
- [ ] Auto-scaling configured (if applicable)

### Disaster Recovery

- [ ] Backup tested and verified
- [ ] Restore procedure tested
- [ ] Recovery time objective (RTO) met
- [ ] Recovery point objective (RPO) met
- [ ] Failover procedure tested

## Test Reports

### Generate Comprehensive Test Report

```bash
#!/bin/bash
# Generate complete test report

REPORT_DIR="reports/phase5_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$REPORT_DIR"

echo "Generating Phase 5 Test Report..."

# 1. Run data validation
echo "1. Data Validation..."
python scripts/validate_data.py --export-report "$REPORT_DIR/validation.json" > "$REPORT_DIR/validation.log" 2>&1

# 2. Run performance tests
echo "2. Performance Testing..."
./scripts/run_performance_tests.sh > "$REPORT_DIR/performance.log" 2>&1

# 3. Run unit tests
echo "3. Unit Tests..."
pytest tests/ -v --tb=short > "$REPORT_DIR/unit_tests.log" 2>&1

# 4. Health check
echo "4. Health Check..."
curl -s http://localhost:8000/health/detailed | jq > "$REPORT_DIR/health.json"

# 5. Load test
echo "5. Load Testing..."
ab -n 1000 -c 10 http://localhost:8000/ > "$REPORT_DIR/load_test.log" 2>&1

# 6. Generate summary
echo "6. Generating Summary..."
cat > "$REPORT_DIR/summary.txt" <<EOF
Phase 5 Testing Summary
Generated: $(date)

Reports included:
- validation.json: Data validation results
- validation.log: Data validation detailed log
- performance.log: Performance test results
- unit_tests.log: Unit test results
- health.json: Current health status
- load_test.log: Load test results

Review each file for detailed results.
EOF

echo "Report generated in: $REPORT_DIR"
```

## Acceptance Sign-Off

Once all tests pass:

1. Document test results
2. Archive test reports
3. Update deployment documentation
4. Get stakeholder approval
5. Schedule production deployment
6. Communicate to team

Phase 5 is complete when:
- ✅ All validation tests pass
- ✅ Performance meets requirements
- ✅ Parallel operation verified
- ✅ Production deployment successful
- ✅ Monitoring operational
- ✅ Team trained and documentation complete
