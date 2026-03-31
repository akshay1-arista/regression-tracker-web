"""
MCP server for Regression Tracker Web.

Exposes regression test data to Claude via the Model Context Protocol.
Mounted at /mcp in the FastAPI app using Streamable HTTP transport.

Typical Claude workflows:
  list_releases() → get_parent_jobs(release) → get_job_stats(release, parent_job_id)
  → get_failing_tests(release, module, job_id) → get_failure_details(release, module, job_id)

  get_bug_breakdown(release, parent_job_id) → get_bug_details(release, parent_job_id, module)
  → get_affected_tests(release, parent_job_id, module, defect_id)

  compare_parent_jobs(release, parent_job_id_a, parent_job_id_b)
  → module-level pass rate deltas + test-level diff (new failures, resolved, persistent)
"""
import logging
from datetime import datetime
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import case, func

from app.database import get_db_context
from app.models.db_models import Job, Module, Release, TestResult, TestStatusEnum
from app.services import data_service

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Regression Tracker",
    instructions=(
        "Use these tools to query regression test data from the Regression Tracker. "
        "Typical workflow: list_releases() → get_parent_jobs(release) → "
        "get_job_stats(release, parent_job_id) to see per-module pass/fail breakdown. "
        "Then get_failing_tests(release, module, job_id) for specific failures. "
        "For bug analysis: get_bug_breakdown(release, parent_job_id) → "
        "get_bug_details(release, parent_job_id, module) → "
        "get_affected_tests(release, parent_job_id, module, defect_id). "
        "For trends: get_trend(release, module) for historical pass rates. "
        "For failure reasons: get_failure_details(release, module, job_id) returns the actual "
        "error message/traceback for each failing test. "
        "For cross-run comparison: compare_parent_jobs(release, id_a, id_b) shows which modules "
        "improved/degraded and which individual tests changed status between two runs."
    ),
)


def _to_serializable(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable types (datetime, enum) to strings."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_serializable(item) for item in obj]
    if hasattr(obj, "value"):  # enum
        return obj.value
    return obj


# ============================================================================
# Release & Module discovery
# ============================================================================

@mcp.tool()
def list_releases() -> list[dict]:
    """List all releases being tracked (e.g., 7.0, 6.4, 6.1)."""
    with get_db_context() as db:
        releases = data_service.get_all_releases(db)
        return [{"name": r.name, "is_active": r.is_active} for r in releases]


@mcp.tool()
def list_modules(release: str) -> list[dict]:
    """List all modules for a release (e.g., business_policy, routing, sdwan)."""
    with get_db_context() as db:
        modules = data_service.get_modules_for_release(db, release)
        return [{"name": m.name} for m in modules]


# ============================================================================
# Summary & parent job navigation
# ============================================================================

@mcp.tool()
def get_summary(release: str) -> dict:
    """
    Get high-level summary statistics for all modules in a release.
    Returns total runs, latest run stats, and average pass rate.
    """
    with get_db_context() as db:
        result = data_service.get_all_modules_summary_stats(db, release)
        return _to_serializable(result)


@mcp.tool()
def get_parent_jobs(release: str, limit: int = 10) -> list[str]:
    """
    Get recent parent job IDs for a release, most recent first.
    A parent job ID identifies a complete test run that spawned all module jobs.
    Use these IDs with get_job_stats() and get_bug_breakdown().
    """
    with get_db_context() as db:
        return data_service.get_latest_parent_job_ids(db, release, limit=limit)


@mcp.tool()
def get_job_stats(release: str, parent_job_id: str) -> dict:
    """
    Get aggregated stats and per-module breakdown for a complete test run.

    Returns:
      summary: overall total/passed/failed/skipped counts and pass rate
      module_breakdown: per-module stats (sorted alphabetically)

    The module_breakdown entries include individual job_id fields that can be
    passed to get_failing_tests() to drill into specific failures.
    """
    with get_db_context() as db:
        aggregated = data_service.get_aggregated_stats_for_parent_job(
            db, release, parent_job_id
        )
        breakdown = data_service.get_module_breakdown_for_parent_job(
            db, release, parent_job_id
        )
        return _to_serializable({"summary": aggregated, "module_breakdown": breakdown})


# ============================================================================
# Test results
# ============================================================================

@mcp.tool()
def get_failing_tests(
    release: str,
    module: str,
    job_id: str,
    limit: int = 50,
) -> list[dict]:
    """
    Get failing tests for a specific module job.

    To find the job_id: call get_job_stats(release, parent_job_id) and look at
    the module_breakdown entries for the module you want.

    Returns test name, priority, testcase_module, file_path, and duration.
    """
    with get_db_context() as db:
        results = data_service.get_test_results_for_job(
            db,
            release,
            module,
            job_id,
            status_filter=[TestStatusEnum.FAILED],
        )
        return [
            {
                "test_name": r.test_name,
                "status": r.status.value,
                "priority": r.priority,
                "testcase_module": r.testcase_module,
                "file_path": r.file_path or "",
                "duration": r.duration,
            }
            for r in results[:limit]
        ]


# ============================================================================
# Trend analysis
# ============================================================================

@mcp.tool()
def get_trend(release: str, module: str, limit: int = 10) -> list[dict]:
    """
    Get historical pass rate trend for a module (chronological order).
    Returns job_id, pass_rate, total, passed, and failed counts per run.
    Useful for spotting regressions or improvements over time.
    """
    with get_db_context() as db:
        return data_service.get_pass_rate_history(db, release, module, limit=limit)


# ============================================================================
# Bug tracking
# ============================================================================

@mcp.tool()
def get_bug_breakdown(
    release: str,
    parent_job_id: str,
    module: Optional[str] = None,
) -> list[dict]:
    """
    Get VLEI/VLENG bug counts per module for a test run.
    Shows how many distinct bugs affect each module and how many tests are impacted.
    Optionally filter to a specific module.

    Returns: module_name, vlei_count, vleng_count, affected_test_count, total_bug_count.
    """
    with get_db_context() as db:
        return data_service.get_bug_breakdown_for_parent_job(
            db, release, parent_job_id, module_filter=module
        )


@mcp.tool()
def get_bug_details(
    release: str,
    parent_job_id: str,
    module: str,
    bug_type: Optional[str] = None,
) -> list[dict]:
    """
    Get detailed bug information for a module in a test run.
    Set bug_type to 'VLEI' or 'VLENG' to filter by type (or omit for all bugs).
    Returns defect_id, status, summary, url, priority, and affected_test_count.
    """
    with get_db_context() as db:
        return data_service.get_bug_details_for_module(
            db, release, parent_job_id, module, bug_type=bug_type
        )


@mcp.tool()
def get_affected_tests(
    release: str,
    parent_job_id: str,
    module: str,
    defect_id: str,
) -> list[dict]:
    """
    Get tests blocked or affected by a specific bug (e.g., 'VLEI-12345').
    Returns testcase_name, priority, status, test_case_id, and file_path.
    Results are sorted by priority (P0 first), then alphabetically.
    """
    with get_db_context() as db:
        return data_service.get_affected_tests_for_bug(
            db, release, parent_job_id, module, defect_id
        )


# ============================================================================
# Failure details & cross-run comparison
# ============================================================================

@mcp.tool()
def get_failure_details(
    release: str,
    module: str,
    job_id: str,
    limit: int = 20,
) -> list[dict]:
    """
    Get failure messages/tracebacks for failed tests in a specific job.
    Use this after get_failing_tests() to understand WHY tests are failing.

    Returns test_name, priority, was_rerun, rerun_still_failed, and
    failure_message (truncated to 2000 chars if very long).
    """
    with get_db_context() as db:
        results = data_service.get_test_results_for_job(
            db,
            release,
            module,
            job_id,
            status_filter=[TestStatusEnum.FAILED],
        )
        return [
            {
                "test_name": r.test_name,
                "priority": r.priority,
                "was_rerun": r.was_rerun,
                "rerun_still_failed": r.rerun_still_failed,
                "failure_message": (r.failure_message or "")[:2000],
            }
            for r in results[:limit]
        ]


@mcp.tool()
def compare_parent_jobs(
    release: str,
    parent_job_id_a: str,
    parent_job_id_b: str,
) -> dict:
    """
    Compare two parent job runs side-by-side.

    Returns:
      module_comparison: per-module pass rate delta and failure count delta
        (sorted by magnitude of change — biggest regressions/improvements first)
      test_diff: test-level status changes across all modules
        - new_failures: tests that PASSED in A but FAILED in B
        - resolved: tests that FAILED in A but PASSED in B
        - persistent_failures: tests that FAILED in both A and B
        (each entry has test_name, priority, testcase_module)

    Tip: use get_parent_jobs() to find valid parent_job_id values.
    """
    with get_db_context() as db:
        # --- Module-level comparison ---
        breakdown_a = data_service.get_module_breakdown_for_parent_job(
            db, release, parent_job_id_a
        )
        breakdown_b = data_service.get_module_breakdown_for_parent_job(
            db, release, parent_job_id_b
        )
        a_by_mod = {m["module_name"]: m for m in breakdown_a}
        b_by_mod = {m["module_name"]: m for m in breakdown_b}

        module_comparison = []
        for mod in sorted(set(a_by_mod) | set(b_by_mod)):
            a = a_by_mod.get(mod, {})
            b = b_by_mod.get(mod, {})
            module_comparison.append({
                "module": mod,
                "job_a": {
                    "failed": a.get("failed", 0),
                    "passed": a.get("passed", 0),
                    "pass_rate": round(a.get("pass_rate", 0.0), 1),
                },
                "job_b": {
                    "failed": b.get("failed", 0),
                    "passed": b.get("passed", 0),
                    "pass_rate": round(b.get("pass_rate", 0.0), 1),
                },
                "pass_rate_delta": round(
                    b.get("pass_rate", 0.0) - a.get("pass_rate", 0.0), 1
                ),
                "failed_delta": b.get("failed", 0) - a.get("failed", 0),
            })
        module_comparison.sort(
            key=lambda x: abs(x["pass_rate_delta"]), reverse=True
        )

        # --- Test-level diff ---
        # Collect all test results for each parent job in two bulk queries
        def _fetch_test_statuses(parent_job_id: str) -> dict[str, dict]:
            """Return {test_name: {status, priority, testcase_module}} for a parent job."""
            jobs = data_service.get_jobs_by_parent_job_id(db, release, parent_job_id)
            if not jobs:
                return {}
            job_ids = [j.id for j in jobs]
            rows = (
                db.query(
                    TestResult.test_name,
                    TestResult.status,
                    TestResult.priority,
                    TestResult.testcase_module,
                )
                .filter(
                    TestResult.job_id.in_(job_ids),
                    TestResult.is_removed == False,  # noqa: E712
                )
                .all()
            )
            # If a test appears multiple times (across modules), keep last seen
            return {
                r.test_name: {
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                    "priority": r.priority,
                    "testcase_module": r.testcase_module,
                }
                for r in rows
            }

        tests_a = _fetch_test_statuses(parent_job_id_a)
        tests_b = _fetch_test_statuses(parent_job_id_b)

        new_failures, resolved, persistent_failures = [], [], []
        all_tests = set(tests_a) | set(tests_b)

        for name in all_tests:
            a_info = tests_a.get(name)
            b_info = tests_b.get(name)
            a_failed = a_info and a_info["status"] == "FAILED"
            b_failed = b_info and b_info["status"] == "FAILED"
            a_passed = a_info and a_info["status"] == "PASSED"
            b_passed = b_info and b_info["status"] == "PASSED"

            entry = {
                "test_name": name,
                "priority": (b_info or a_info or {}).get("priority"),
                "testcase_module": (b_info or a_info or {}).get("testcase_module"),
            }
            if a_passed and b_failed:
                new_failures.append(entry)
            elif a_failed and b_passed:
                resolved.append(entry)
            elif a_failed and b_failed:
                persistent_failures.append(entry)

        # Sort each list by priority then test name for readability
        from app.constants import PRIORITY_ORDER
        def _sort_key(e):
            return (PRIORITY_ORDER.get(e.get("priority") or "UNKNOWN", 99), e["test_name"])

        new_failures.sort(key=_sort_key)
        resolved.sort(key=_sort_key)
        persistent_failures.sort(key=_sort_key)

        return {
            "parent_job_id_a": parent_job_id_a,
            "parent_job_id_b": parent_job_id_b,
            "module_comparison": module_comparison,
            "test_diff": {
                "new_failures": new_failures,
                "resolved": resolved,
                "persistent_failures": persistent_failures,
                "summary": {
                    "new_failures": len(new_failures),
                    "resolved": len(resolved),
                    "persistent_failures": len(persistent_failures),
                },
            },
        }
