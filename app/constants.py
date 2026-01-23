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

# Flaky Test Detection Configuration
FLAKY_DETECTION_JOB_WINDOW = 5
"""
Number of most recent jobs to analyze for flaky test detection.

A test is considered flaky if it has both passes and failures within this window.
This value is used in dashboard flaky statistics and affects the exclude_flaky
pass rate calculation.
"""

DEFAULT_TREND_JOB_DISPLAY_LIMIT = 5
"""
Default number of recent jobs to display in the trend view.

Users can override this via the job display limit dropdown (5, 10, 15, 20, or All).
Defaults to 5 to match the flaky detection window for consistency.
"""
