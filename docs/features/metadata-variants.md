# Metadata Variants - Global vs Release-Specific

## Overview

The regression tracker supports **metadata variants** to handle cases where test metadata differs across releases. This document explains how metadata variants work and what to expect in the UI.

## How It Works

### Storage Model

The system uses a **hybrid storage model** that balances efficiency with flexibility:

1. **Global Metadata** (Default)
   - Serves as the baseline metadata for all tests
   - Stored with `release_id = NULL`
   - Applies to all releases unless overridden

2. **Release-Specific Metadata** (When Needed)
   - Created ONLY when test metadata differs from Global
   - Stored with `release_id = <specific release>`
   - Overrides Global metadata for that release

### Example

```
test_bgp_routing:
  Global:     priority=P1, topology=5-site
  7.0:        (no record - uses Global)
  6.4:        (no record - uses Global)

test_priority_override:
  Global:     priority=P1, topology=5-site
  7.0:        priority=P0, topology=5-site  ← Created because priority differs
  6.4:        (no record - uses Global)
```

## UI Behavior

### Search Page - Execution History Modal

When viewing test execution history, the metadata section shows **tabs** for each variant:

**Scenario 1: Test with Global metadata only**
```
┌─────────────────────────────────┐
│ Test Metadata                   │
├─────────────────────────────────┤
│ [Global]                        │  ← Only one tab
│                                 │
│ Priority: P1                    │
│ Topology: 5-site                │
│ ...                             │
└─────────────────────────────────┘
```

**Scenario 2: Test with multiple variants**
```
┌─────────────────────────────────┐
│ Test Metadata (varies by release)
├─────────────────────────────────┤
│ [Global] [7.0] [6.4]            │  ← Multiple tabs
│                                 │
│ Priority: P1 ⚠️                  │  ← Warning icon = differs
│ Topology: 5-site                │
│ ...                             │
└─────────────────────────────────┘
```

### Interpreting the Tabs

- **Only "Global" tab visible**: Test metadata is **identical across all releases**
- **Multiple tabs visible**: Test metadata **differs between releases**
- **⚠️ Warning icon**: Field value differs from Global for this release

## When Are Release-Specific Records Created?

During Git metadata sync, release-specific records are created when:

1. **Test metadata differs from Global**, including:
   - Priority changes (P1 → P0)
   - Topology changes (5-site → 3-site)
   - Test state changes (PROD → STAGING)
   - Module changes
   - Any other metadata field

2. **Test doesn't exist in Global** (new test in this release)

## Database Statistics

After sync, you can check metadata distribution:

```bash
python scripts/verify_metadata_distribution.py
```

**Typical distribution:**
```
Total metadata records: 10,900
Global metadata: 10,895 (99.9%)
Release-specific metadata: 5 (0.1%)
```

This is **normal and expected** - most tests have identical metadata across releases.

## Verifying Specific Tests

To check metadata variants for a specific test:

```bash
python scripts/check_metadata_variants.py <testcase_name>
```

**Example output:**
```
Found 3 metadata variant(s):

Variant #1: Global
  Priority: P1
  Topology: 3-site

Variant #2: 7.0
  Priority: P0  ← Differs from Global
  Topology: 3-site

Variant #3: 6.4
  Priority: P2  ← Differs from Global
  Topology: 3-site
```

## Common Questions

### Q: Why do most tests only show "Global" tab?

**A:** Because metadata is identical across releases for most tests. This is expected and normal.

### Q: How do I force release-specific metadata for all tests?

**A:** This is not recommended (creates ~40,000 duplicate records), but you can modify the sync logic in `git_metadata_sync_service.py` to always create release-specific records.

### Q: What if I want to manually set release-specific priority?

**A:** You can manually insert/update records in the `testcase_metadata` table with a specific `release_id`. The sync will respect manual changes and not overwrite them.

### Q: How do I see which tests have release-specific variants?

**A:** Run the verification script:
```bash
python scripts/verify_metadata_distribution.py
```

Look for the "TESTS WITH MULTIPLE METADATA VARIANTS" section.

## Implementation Details

### Git Metadata Sync Logic

When syncing for a specific release (e.g., 7.0):

1. **Fetch existing metadata** (Global + release-specific for this release)
2. **Discover tests** from Git repository
3. **Compare** discovered data with existing:
   - If existing is **Global** AND data differs → **CREATE** new release-specific record
   - If existing is **release-specific** → **UPDATE** it
   - If existing is **Global** AND data identical → **No action** (use Global)
4. **Apply changes** to database

### Database Schema

```sql
-- Metadata table structure
CREATE TABLE testcase_metadata (
    id INTEGER PRIMARY KEY,
    testcase_name TEXT NOT NULL,
    release_id INTEGER,  -- NULL = Global, otherwise specific release
    priority TEXT,
    topology TEXT,
    ...
    FOREIGN KEY (release_id) REFERENCES releases(id)
);
```

### API Response Format

Search API returns all variants:

```json
{
  "testcase_name": "test_example",
  "metadata_variants": [
    {
      "release": "Global",
      "priority": "P1",
      "topology": "5-site"
    },
    {
      "release": "7.0",
      "priority": "P0",
      "topology": "5-site"
    }
  ]
}
```

## Troubleshooting

### Issue: All tests show only Global tab

**Diagnosis:**
```bash
python scripts/verify_metadata_distribution.py
```

If you see:
```
Release-specific metadata: 0-5 records
```

**Possible causes:**
1. ✅ **Normal** - Tests have identical metadata across releases
2. ❌ **Git sync not run** - Run sync from Admin page
3. ❌ **All releases use same branch** - Check release configuration

### Issue: Release-specific metadata created for identical data

**This should NOT happen** with the current implementation. If you see release-specific records with identical data to Global, this indicates a bug in the sync logic.

**To investigate:**
```bash
# Find tests with duplicate metadata
python -c "
from app.database import SessionLocal
from app.models.db_models import TestcaseMetadata, Release
from sqlalchemy import and_

db = SessionLocal()
tests = db.query(TestcaseMetadata.testcase_name).group_by(
    TestcaseMetadata.testcase_name
).having(db.func.count(TestcaseMetadata.id) > 1).all()

for test in tests[:10]:
    variants = db.query(TestcaseMetadata, Release.name).outerjoin(
        Release
    ).filter(TestcaseMetadata.testcase_name == test[0]).all()

    print(f'{test[0]}:')
    for v, r in variants:
        print(f'  {r or \"Global\"}: {v.priority}, {v.topology}')
"
```

## Related Documentation

- [Git Metadata Sync Service](../dev/git-metadata-sync.md)
- [Search API Documentation](../api/search-endpoints.md)
- [Admin Metadata Sync Guide](../admin/metadata-sync.md)
