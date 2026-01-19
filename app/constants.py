"""
Application-wide constants.

Defines shared constants used across the application to avoid magic strings
and ensure consistency.
"""

# Dashboard Module Identifiers
ALL_MODULES_IDENTIFIER = "__all__"
"""
Special identifier for the 'All Modules' aggregated dashboard view.

When used as a module name in dashboard endpoints, this triggers aggregation
logic that groups jobs by parent_job_id to show release-wide statistics.
"""

# Priority Levels
PRIORITY_LEVELS = ["P0", "P1", "P2", "P3", "UNKNOWN"]
"""Ordered list of test priority levels."""

PRIORITY_ORDER = {
    "P0": 0,
    "P1": 1,
    "P2": 2,
    "P3": 3,
    "UNKNOWN": 4
}
"""Mapping of priority levels to sort order."""
