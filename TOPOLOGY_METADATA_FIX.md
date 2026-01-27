# Topology Metadata Fix

## Problem

When importing jobs via on-demand polling, the **Design Topology** column was showing "N/A" for all test cases in both the trend view and job view tables.

## Root Cause

The import service ([app/services/import_service.py](app/services/import_service.py)) was only enriching test results with the `priority` field from the `testcase_metadata` table, but was **NOT** populating the `topology_metadata` field (design topology).

### Background

The application maintains two separate topology fields:

1. **`test_results.jenkins_topology`** (Execution Topology)
   - Source: JUnit XML from Jenkins artifacts
   - Represents: What topology Jenkins actually ran the test on
   - Example: "5s" (execution context)

2. **`test_results.topology_metadata`** (Design Topology)
   - Source: Denormalized from `testcase_metadata.topology`
   - Represents: What topology the test was designed for
   - Example: "5-site" (design specification)

## Solution

### 1. Import Service Fix (✅ DONE)

Modified [app/services/import_service.py](app/services/import_service.py) to:

- Build a `topology_lookup` dictionary from `testcase_metadata.topology` (similar to existing `priority_lookup`)
- Set `topology_metadata` field when creating new test results
- Update `topology_metadata` field when updating existing test results

**Changes made:**
- Line 251-265: Added topology to metadata query and created `topology_lookup`
- Line 290-293: Updated existing records to set `topology_metadata` from lookup
- Line 299-322: Set `topology_metadata` for new records from lookup

### 2. Backfill Script (✅ CREATED)

Created [scripts/backfill_topology_metadata.py](scripts/backfill_topology_metadata.py) to update existing test results.

## How to Fix Your Data

### Option 1: Backfill All Test Results (Recommended)

```bash
# Dry run to preview changes
python3 scripts/backfill_topology_metadata.py --dry-run

# Apply changes
python3 scripts/backfill_topology_metadata.py
```

Expected output:
```
Starting topology_metadata backfill process
Found 12,345 test results to process
Querying metadata for 2,567 unique test names
Found metadata for 2,234 test names

====================================================
SUMMARY
====================================================
Total test results processed: 12,345
Updated with topology:        10,890
No metadata found:            1,455
Already correct/skipped:      0
====================================================

✓ Topology metadata backfill completed successfully!
```

### Option 2: Backfill Specific Release

```bash
# Backfill only 6.1 release
python3 scripts/backfill_topology_metadata.py --release 6.1

# Backfill specific job in a release
python3 scripts/backfill_topology_metadata.py --release 6.1 --job 144
```

### Option 3: Re-import Jobs (Alternative)

If you prefer to re-import the jobs entirely:

```bash
# Delete the specific job(s) from the database first
# Then trigger on-demand polling again

# The new import will automatically populate topology_metadata
```

## Verification

After running the backfill script:

1. Open the **Trends** page: http://localhost:8000/trends
   - Filter by a test case
   - Check the "Design Topology" column
   - Should show values like "5-site", "3-site-ipv6", etc.

2. Open a **Job Details** page: http://localhost:8000/jobs/{job_id}
   - Check the "Design Topology" column
   - Should show topology values instead of "N/A"

## Future Imports

All **new jobs** imported after this fix will automatically have `topology_metadata` populated during import. No manual backfill needed.

## Testing

Run the import service tests to verify the fix:

```bash
python3 -m pytest tests/test_import_service.py -v
```

All 16 tests should pass ✅

## Notes

- The backfill script uses **normalized test names** to handle parameterized tests (e.g., `test_foo[param]` → `test_foo`)
- Test cases without metadata entries will still show "N/A" (expected behavior)
- The script is safe to run multiple times (idempotent)
- Use `--dry-run` flag to preview changes without committing
