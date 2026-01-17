# Priority Filtering and Global Search Guide

This guide explains how to use the priority-based filtering and global test case search features in the Regression Tracker.

## Table of Contents

1. [Priority-Based Filtering](#priority-based-filtering)
2. [Global Test Case Search](#global-test-case-search)
3. [Dashboard Priority Statistics](#dashboard-priority-statistics)
4. [Best Practices](#best-practices)

---

## Priority-Based Filtering

Test cases in the Regression Tracker are classified by priority levels:

- **P0**: Critical - Core functionality, must pass
- **P1**: High - Important features
- **P2**: Medium - Secondary features
- **P3**: Low - Nice-to-have features
- **Unknown**: Test cases without assigned priority

### Filtering in Trends View

The trends page allows you to filter test cases by one or more priorities:

1. Navigate to **Trends** for any release/module (e.g., `/trends/7.0/business_policy`)
2. In the **Priority** section, click the priority chips you want to filter by
3. Multiple priorities can be selected simultaneously
4. Active filters show a checkmark (✓)
5. Click **Clear All Filters** to remove all active filters

**Example Use Cases:**

- Filter by `P0` to see only critical test trends
- Select `P0` + `P1` to focus on high-priority tests
- Select `Unknown` to identify tests that need priority assignment

### Filtering in Job Details View

The job details page provides similar multi-select filtering:

1. Navigate to any job details page (e.g., `/jobs/7.0/business_policy/11`)
2. Use the **Priority** filter chips to select one or more priorities
3. Combine with **Status** filters (PASSED, FAILED, SKIPPED, ERROR) for refined results
4. Use the **Search** box to further narrow down results by test name

**Filter Combinations:**

- **Status: FAILED** + **Priority: P0** → View only failed critical tests
- **Status: PASSED,FAILED** + **Priority: P0,P1** → All non-skipped high-priority tests
- **Status: FAILED** + **Search: "routing"** + **Priority: P0** → Failed P0 routing tests

### How Filters Work

- **Debounced Updates**: Filters trigger API calls after 300ms of inactivity to prevent excessive requests
- **URL Parameters**: Filter state is preserved in the URL (can be bookmarked or shared)
- **Pagination**: Works seamlessly with filters - page counts reflect filtered results
- **Performance**: Priority filters use indexed database columns for fast queries

---

## Global Test Case Search

The global search feature allows you to search for test cases across all releases and modules.

### Accessing Search

- Click **Search** in the navigation bar
- Direct URL: `/search`

### Search Capabilities

You can search by:

1. **Test Case ID** (e.g., `TC-1234`)
2. **TestRail ID** (e.g., `C12345`)
3. **Test Name** (partial or full, e.g., `biz_policy_pre_nat`)

### Autocomplete Feature

As you type (minimum 2 characters), the search provides real-time suggestions:

- Displays top 10 matching test cases
- Shows: Test name, Test Case ID, and Priority badge
- **Keyboard navigation**:
  - `Arrow Down` / `Arrow Up`: Navigate suggestions
  - `Enter`: Select highlighted suggestion and search
  - `Escape`: Close suggestions dropdown
- **Mouse navigation**: Click any suggestion to select and search

### Search Results

Results include:

- **Test Metadata**:
  - Test Name
  - Test Case ID
  - TestRail ID
  - Priority (color-coded badge)
  - Component
  - Automation Status
  - Total Executions count

- **Actions**:
  - **View History** button: Opens modal with detailed execution history

### Execution History Modal

Clicking **View History** opens a modal showing:

1. **Test Metadata** (Name, IDs, Priority, Component)

2. **Statistics**:
   - Total Runs
   - Passed / Failed / Skipped / Error counts
   - Pass Rate percentage

3. **Recent Executions** (paginated, 100 records per page):
   - Job ID (clickable link to job details)
   - Release / Module
   - Version
   - Status (with rerun indicators)
   - Topology
   - Created timestamp

4. **Pagination**: Navigate through execution history with Previous/Next buttons

### Example Workflows

**Scenario 1: Investigate a Flaky Test**

1. Search for test by name: `test_biz_policy_icmp_probe`
2. Click **View History**
3. Review statistics: If pass rate is 50-80%, it's likely flaky
4. Check recent executions for patterns (specific topology? specific version?)

**Scenario 2: Find All Tests for a Feature**

1. Search by component or partial name: `routing_ospf`
2. Review all matching tests with their priorities
3. Click individual tests to see their execution history

**Scenario 3: Verify Test Coverage**

1. Search by Test Case ID: `TC-46809`
2. Verify it has execution history across multiple jobs
3. Check pass rate to assess stability

---

## Dashboard Priority Statistics

The dashboard shows a breakdown of test results by priority for the latest job.

### Viewing Priority Stats

1. Navigate to the **Dashboard** (home page)
2. Select **Release**, **Version** (optional), and **Module**
3. View the **Test Results by Priority (Latest Job)** table

### Statistics Table

Displays for each priority level:

- **Priority**: Color-coded priority badge
- **Total**: Total tests run with this priority
- **Passed**: Count of passed tests
- **Failed**: Count of failed tests
- **Skipped**: Count of skipped tests
- **Error**: Count of tests with errors
- **Pass Rate**: Percentage calculated as `(Passed / (Total - Skipped)) × 100`

**Color Coding:**

- **Pass Rate ≥ 90%**: Green (high quality)
- **70% ≤ Pass Rate < 90%**: Yellow (medium quality)
- **Pass Rate < 70%**: Red (needs attention)

### Use Cases

- **Release Health Check**: Quickly assess if P0/P1 tests are passing
- **Priority Triage**: Identify which priority level has the most failures
- **Trend Monitoring**: Compare pass rates across jobs by checking different versions

---

## Best Practices

### Filtering Best Practices

1. **Start Broad, Then Narrow**: Begin with priority filters, then add status/search
2. **Bookmark Important Views**: Save filtered URLs for quick access
   - Example: `<base_url>/jobs/7.0/business_policy/11?priorities=P0&statuses=FAILED`
3. **Use Combined Filters**: Don't rely on just one filter - combine for precise results
4. **Check Unknown Priority**: Periodically filter by `Unknown` to identify unclassified tests

### Search Best Practices

1. **Use Autocomplete**: Start typing and let autocomplete guide you
2. **Search by ID When Possible**: More precise than name-based searches
3. **Partial Matches Work**: `biz_policy` matches `test_biz_policy_pre_nat_many_to_one_snat_profile`
4. **Case Insensitive**: Search is case-insensitive (`TEST_BIZ` = `test_biz`)
5. **Underscore Matching**: Underscores are treated as literal characters (not wildcards)

### Dashboard Best Practices

1. **Check Priority Stats First**: Before drilling into details, assess overall health
2. **Focus on P0/P1 Failures**: These are usually release blockers
3. **Compare Across Jobs**: Check priority stats for multiple jobs to identify trends
4. **Monitor Pass Rates**: Set a threshold (e.g., P0 must be ≥95%) and track compliance

---

## API Endpoints

For programmatic access or integration:

### Priority Filtering APIs

**Trends with Priority Filter:**
```
GET /api/v1/trends/{release}/{module}?priorities=P0,P1
```

**Job Tests with Multi-Select Filters:**
```
GET /api/v1/jobs/{release}/{module}/{job_id}/tests?statuses=FAILED&priorities=P0,P1
```

**Priority Statistics:**
```
GET /api/v1/dashboard/priority-stats/{release}/{module}/{job_id}
```

### Search APIs

**Autocomplete:**
```
GET /api/v1/search/autocomplete?q={query}&limit=10
```

**Global Search:**
```
GET /api/v1/search/testcases?q={query}&limit=50
```

**Test Case Details:**
```
GET /api/v1/search/testcases/{testcase_name}?limit=100&offset=0
```

---

## Troubleshooting

### Filters Not Working

- **Issue**: Filters don't seem to apply
- **Solution**:
  - Check that you've clicked the filter chip (should show checkmark)
  - Wait 300ms for debounce - results update automatically
  - Check browser console for errors
  - Verify you're not mixing incompatible filters

### Search Not Finding Tests

- **Issue**: Search returns no results for known test
- **Solution**:
  - Ensure query is at least 1 character (autocomplete requires 2)
  - Try searching by Test Case ID instead of name
  - Verify test exists in database (check job details)
  - Try partial match instead of full name

### Autocomplete Not Showing

- **Issue**: Autocomplete dropdown doesn't appear
- **Solution**:
  - Type at least 2 characters
  - Wait 200ms for debounce
  - Click in the search box to refocus
  - Check browser console for network errors
  - Verify autocomplete endpoint is reachable

### Priority Shows as "Unknown"

- **Issue**: All test priorities show as "Unknown"
- **Solution**:
  - This means test cases haven't been imported from the master CSV
  - Contact admin to run: `POST /api/v1/admin/testcase-metadata/import`
  - After import, priorities will backfill automatically

---

## FAQ

**Q: Can I filter by priority in the flat view?**
A: Yes, priority filters work in both flat and grouped views in job details.

**Q: How many priorities can I select at once?**
A: Unlimited. You can select all priorities if needed.

**Q: Does search work across all releases?**
A: Yes, global search searches across all releases and modules simultaneously.

**Q: How is pass rate calculated?**
A: Pass Rate = (Passed Tests / (Total Tests - Skipped Tests)) × 100

**Q: What happens if I search for a test that doesn't exist?**
A: You'll see an empty state message with search tips.

**Q: Can I combine priority filter with flaky/always_failing filters in trends?**
A: Yes, all filters can be combined for precise trend analysis.

**Q: How long does autocomplete take to respond?**
A: Autocomplete is optimized to respond in <100ms for fast, responsive suggestions.

---

## Related Documentation

- [User Guide](USER_GUIDE.md) - General application usage
- [API Documentation](API.md) - Complete API reference
- [Admin Guide](ADMIN_GUIDE.md) - Priority import and maintenance

---

**Last Updated**: 2026-01-18
**Version**: 1.0.0
