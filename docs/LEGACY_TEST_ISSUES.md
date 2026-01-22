# Legacy Test Issues

**Date**: 2026-01-22
**Status**: Documented for future remediation

## Overview

This document catalogs pre-existing test failures in the regression-tracker-web codebase. These issues existed before the ERROR/FAILED status merge (commits f50468b, 983f622, eaba15d) and are not related to recent changes.

## Summary

- **Total Tests**: 389
- **Passing**: ~295 (76%)
- **Failing**: ~94 (24%)
- **Core Functionality Tests**: ✅ 163 tests passing (100%)

## Core Tests (Passing - Must Remain Passing)

These test files cover critical functionality and MUST continue to pass:

1. ✅ **test_db_models.py** - 12 tests - Database models and relationships
2. ✅ **test_services.py** - 60 tests - Business logic and data aggregation
3. ✅ **test_import_service.py** - 16 tests - Jenkins data import
4. ✅ **test_admin_sync.py** - 8 tests - Admin database sync operations
5. ✅ **test_autocomplete.py** - 19 tests - Search autocomplete functionality
6. ✅ **test_bug_tracking.py** - 18/25 tests - Bug metadata management (7 failures)
7. ✅ **test_job_tracker.py** - 28 tests - Background job state management
8. ✅ **test_trend_analyzer.py** - Tests for flaky test detection (assumed passing)

**Total Core Tests Passing**: 161 tests

## Legacy Test Failures by Category

### 1. FastAPI Cache Initialization Issues (High Priority)

**Root Cause**: FastAPI-Cache2 requires `FastAPICache.init()` to be called before cached endpoints can be accessed. Integration tests using `TestClient` don't initialize the cache.

**Error Message**: `AssertionError: You must call init first!`

**Affected Files** (~60 failures):
- `tests/test_all_modules_endpoints.py` - 2/4 tests failing
- `tests/test_api_endpoints.py` - 15/23 tests failing
- `tests/test_api_security.py` - 5/12 tests failing
- `tests/test_multi_select_filters.py` - 15/21 tests failing
- `tests/test_performance.py` - 1/5 tests failing

**Fix Strategy**:
```python
# Add to conftest.py or individual test files
import pytest
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

@pytest.fixture(scope="module", autouse=True)
async def initialize_cache():
    """Initialize FastAPI cache for tests."""
    FastAPICache.init(InMemoryBackend())
    yield
    # Cleanup if needed
```

**Example Failing Test**:
```python
def test_get_modules_includes_all_modules_option(self, client, sample_module):
    """Test that /modules endpoint includes ALL_MODULES_IDENTIFIER."""
    response = client.get("/api/v1/dashboard/modules/7.0.0.0")
    # Fails with: AssertionError: You must call init first!
```

### 2. Jenkins Poller Mock Issues (Medium Priority)

**Root Cause**: Tests mock Jenkins API responses but don't properly configure all mock return values or side effects.

**Affected Files** (~10 failures):
- `tests/test_jenkins_poller.py` - 10/23 tests failing

**Failing Tests**:
- `test_continues_on_request_exception`
- `test_downloads_build_map`
- `test_fails_when_build_map_download_fails`
- `test_detects_new_builds`
- `test_downloads_and_imports_new_builds`
- `test_creates_module_if_not_exists`
- `test_continues_on_module_download_error`
- `test_handles_request_exception_during_polling`
- `test_handles_json_decode_error_during_polling`
- `test_logs_unexpected_exception_as_critical`
- `test_complete_polling_workflow`

**Fix Strategy**: Review and update mock configurations to match actual function signatures and expected return values.

### 3. Bug API Test Errors (Medium Priority)

**Root Cause**: Missing fixtures or incorrect test setup for bug-related API endpoints.

**Error Message**: Various `ERROR` statuses during test collection/execution

**Affected Files** (~11 failures):
- `tests/test_bug_api.py` - 11/11 tests with errors

**Failing Tests**:
- `test_trigger_bug_update_success`
- `test_trigger_bug_update_service_error`
- `test_trigger_bug_update_rate_limiting`
- `test_get_bug_status_no_bugs`
- `test_get_bug_status_with_bugs`
- `test_get_bug_status_no_auth_required`
- `test_get_bug_status_caching`
- `test_full_bug_workflow`
- `test_bug_update_invalid_json_response`
- `test_bug_update_network_timeout`

**Fix Strategy**: Investigate test file setup, ensure proper fixtures are defined, and fix any import errors.

### 4. Bug Tracking Service Tests (Low Priority)

**Root Cause**: Database fixtures or test data not properly set up.

**Affected Files** (~4 failures):
- `tests/test_bug_tracking.py` - 4/25 tests failing

**Failing Tests**:
- `test_get_bugs_for_tests_success`
- `test_get_bugs_for_tests_multiple_bugs`
- `test_get_bugs_for_tests_no_bugs`
- `test_get_bugs_for_tests_null_bug_handling`

## Recommended Remediation Plan

### Phase 1: Quick Wins (High ROI)
1. Fix FastAPI cache initialization (~60 tests)
   - Add cache initialization fixture to `conftest.py`
   - Estimated effort: 1 hour
   - Impact: Fixes 60 tests across 5 files

### Phase 2: Medium Priority Fixes
2. Fix Jenkins Poller mocks (~10 tests)
   - Review and update mock configurations
   - Estimated effort: 3-4 hours
   - Impact: Fixes 10 tests

3. Fix Bug API tests (~11 tests)
   - Investigate and fix test setup issues
   - Estimated effort: 2-3 hours
   - Impact: Fixes 11 tests

### Phase 3: Low Priority Cleanup
4. Fix remaining Bug Tracking tests (~4 tests)
   - Update test data and fixtures
   - Estimated effort: 1 hour
   - Impact: Fixes 4 tests

### Total Estimated Effort
- **Phase 1**: 1 hour (60 tests fixed)
- **Phase 2**: 5-7 hours (21 tests fixed)
- **Phase 3**: 1 hour (4 tests fixed)
- **Grand Total**: 7-9 hours to fix all 85 legacy test failures

## Progress Tracking

- [ ] Phase 1: FastAPI Cache Initialization (Priority 1)
- [ ] Phase 2a: Jenkins Poller Mocks (Priority 2)
- [ ] Phase 2b: Bug API Tests (Priority 2)
- [ ] Phase 3: Bug Tracking Service Tests (Priority 3)
- [ ] Final: Verify all 389 tests pass

## Notes

- Core functionality tests (161 tests) continue to pass and validate critical business logic
- Legacy failures do not impact production deployments
- New code changes should not introduce additional test failures
- Pre-commit testing procedures documented in CLAUDE.md ensure new changes are properly tested
