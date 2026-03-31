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
import enum
import logging
from datetime import datetime
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from app.constants import PRIORITY_ORDER
from app.database import get_db_context
from app.models.db_models import TestResult, TestStatusEnum
from app.services import data_service

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Regression Tracker",
    host="0.0.0.0",
    stateless_http=True,
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
        "improved/degraded and which individual tests changed status between two runs. "
        "SINGLE-TEST ANALYSIS: "
        "search_test_results(release, parent_job_id, name) → find a test by partial name. "
        "get_test_failure_analysis(release, test_name, parent_job_id) → one-stop 'why did X fail?' "
        "(combines current status + history + flaky assessment + bugs + metadata). "
        "get_test_history(release, test_name) → last N runs for this test ('was it passing before?'). "
        "get_test_history_cross_release(test_name) → compare across all releases. "
        "get_testcase_info(test_name) → static metadata (priority, component, topology, bugs). "
        "RUN-LEVEL ANALYSIS: "
        "get_module_health_summary(release, parent_job_id) → one-call overview of ALL modules "
        "(failures, new failures, flaky count, bug count, P0/P1 breakdown). "
        "get_new_failures_with_details(release, parent_job_id) → newly broken tests WITH failure messages. "
        "get_flaky_tests(release, parent_job_id) → tests that were rerun in this run. "
        "get_persistent_failures(release, module) → tests failing in every recent run. "
        "PATTERN ANALYSIS: "
        "search_failures_by_pattern(release, parent_job_id, 'connection refused') → find all tests "
        "sharing the same root cause. "
        "get_topology_failure_breakdown(release, module, job_id) → failures grouped by topology."
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
    if isinstance(obj, enum.Enum):
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
def get_all_bug_details(
    release: str,
    parent_job_id: str,
    bug_type: Optional[str] = None,
) -> list[dict]:
    """
    Get bug details for ALL modules in a single query.
    Use this instead of calling get_bug_details() per module when you need
    a complete picture (e.g., to build a CSV or cross-module summary).
    Set bug_type to 'VLEI' or 'VLENG' to filter by type (or omit for all bugs).
    Returns defect_id, bug_type, status, summary, url, priority,
    affected_test_count, priority_breakdown, and module for each entry.
    Results are sorted by module, then affected_test_count descending.
    """
    with get_db_context() as db:
        return data_service.get_all_bug_details_for_run(
            db, release, parent_job_id, bug_type=bug_type
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
# Test search & failure details & cross-run comparison
# ============================================================================

@mcp.tool()
def get_test_history(
    release: str,
    test_name: str,
    limit: int = 10,
) -> list[dict]:
    """
    Get a specific test's execution history across the N most recent parent jobs in a release.
    Directly answers "was this test passing before?"

    Returns one entry per parent job (newest first). Status is "NOT_RUN" when
    the test was absent from that run.

    Each entry includes: parent_job_id, job_id, module, status, failure_message
    (truncated to 500 chars), was_rerun, rerun_still_failed, jenkins_topology, executed_at.
    """
    with get_db_context() as db:
        return _to_serializable(data_service.get_test_execution_history(db, release, test_name, limit=limit))


@mcp.tool()
def get_test_failure_analysis(
    release: str,
    test_name: str,
    parent_job_id: str,
) -> dict:
    """
    One-stop comprehensive analysis for a single test in a specific run.
    The primary tool for answering "why did test X fail?"

    Combines:
    - current_run: status, failure message, topology, rerun info
    - history: last 5 runs (newest first) — was it passing before?
    - flaky_assessment: FLAKY / CONSISTENTLY_FAILING / RECENTLY_BROKEN / STABLE_FAILURE
    - bugs: associated VLEI/VLENG bugs (if any)
    - metadata: priority, component, topology design, file path

    Tip: use search_test_results() first if you don't know the exact test name.
    """
    with get_db_context() as db:
        # Current run details
        current_matches = data_service.search_test_by_name(db, release, parent_job_id, test_name)
        current_run = current_matches[0] if current_matches else None

        # History (last 5 runs)
        history = data_service.get_test_execution_history(db, release, test_name, limit=5)

        # Flaky assessment from history
        statuses = [h["status"] for h in history if h["status"] != "NOT_RUN"]
        if not statuses:
            flaky_assessment = "NO_DATA"
        elif all(s == "FAILED" for s in statuses):
            flaky_assessment = "CONSISTENTLY_FAILING"
        elif statuses[0] == "FAILED" and all(s == "PASSED" for s in statuses[1:]):
            flaky_assessment = "RECENTLY_BROKEN"
        elif "PASSED" in statuses and "FAILED" in statuses:
            flaky_assessment = "FLAKY"
        else:
            flaky_assessment = "STABLE_FAILURE"

        # Metadata
        metadata = data_service.get_testcase_info(db, test_name)

        return _to_serializable({
            "test_name": test_name,
            "current_run": current_run,
            "history": [{"parent_job_id": h["parent_job_id"], "status": h["status"]} for h in history],
            "flaky_assessment": flaky_assessment,
            "bugs": metadata.get("associated_bugs", []) if metadata else [],
            "metadata": {
                k: v for k, v in (metadata or {}).items() if k != "associated_bugs"
            },
        })


@mcp.tool()
def get_test_history_cross_release(
    test_name: str,
    runs_per_release: int = 5,
) -> dict:
    """
    See how a test is performing across ALL releases simultaneously.
    Answers "is this 7.0-specific or broken everywhere?"

    Returns by_release dict with latest_status, pass_rate_last_n, and last_n_statuses
    for each release.
    """
    with get_db_context() as db:
        return _to_serializable(
            data_service.get_test_history_all_releases(db, test_name, runs_per_release=runs_per_release)
        )


@mcp.tool()
def get_testcase_info(
    test_name: str,
) -> dict | None:
    """
    Get complete static metadata for a test case.
    Answers "what is this test?" without needing a specific run.

    Returns: priority, component, test_case_id, testrail_id, automation_status,
    test_state (PROD/STAGING), topology (design), file_path, module,
    and associated_bugs (VLEI/VLENG bugs linked to this test).

    Returns null if the test has no metadata records.
    """
    with get_db_context() as db:
        result = data_service.get_testcase_info(db, test_name)
        return _to_serializable(result) if result else None


@mcp.tool()
def get_new_failures_with_details(
    release: str,
    parent_job_id: str,
    module: Optional[str] = None,
) -> dict:
    """
    Find tests that newly FAILED in this run vs the previous run, WITH failure messages.

    Unlike compare_parent_jobs() which only returns test names, this tool includes
    the actual failure message, topology, and priority for each new failure — providing
    the context needed for triage.

    Returns: parent_job_id, compared_to (previous parent_job_id), new_failure_count,
    and new_failures list sorted by priority then name.
    """
    with get_db_context() as db:
        return _to_serializable(
            data_service.get_new_failures_with_messages(db, release, parent_job_id, module_filter=module)
        )


@mcp.tool()
def get_flaky_tests(
    release: str,
    parent_job_id: str,
    module: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    List tests that were rerun in this run (indicating flaky/unreliable behavior).

    was_rerun=True means the test runner retried the test.
    rerun_still_failed=True means it still failed after retry.

    Returns: test_name, module, priority, was_rerun, rerun_still_failed, final status,
    jenkins_topology.
    """
    with get_db_context() as db:
        return _to_serializable(
            data_service.get_rerun_tests_for_run(
                db, release, parent_job_id, module_filter=module, limit=limit
            )
        )


@mcp.tool()
def get_persistent_failures(
    release: str,
    module: str,
    num_recent_runs: int = 5,
) -> list[dict]:
    """
    Find tests that have been FAILED in every one of the last N runs for a module.
    Answers "what has been broken for a while?" vs newly introduced failures.

    Returns: test_name, priority, consecutive_failures (count), first_seen_failing_parent_job,
    and latest_failure_message.
    Sorted by priority (P0 first) then alphabetically.
    """
    with get_db_context() as db:
        return _to_serializable(
            data_service.get_always_failing_tests(db, release, module, num_recent_runs=num_recent_runs)
        )


@mcp.tool()
def get_topology_failure_breakdown(
    release: str,
    module: str,
    job_id: str,
) -> dict:
    """
    Group test failures by execution topology for a module job.
    Answers "is this failing only on 5-site topologies?" to distinguish
    topology-specific bugs from general failures.

    Returns by_topology dict: each key is a topology name (e.g., "5s", "3s"),
    value is {total, failed, passed, pass_rate, failing_tests}.

    Use get_job_stats() to find job_id values for a specific module.
    """
    with get_db_context() as db:
        grouped = data_service.get_test_results_grouped_by_jenkins_topology(
            db, release, module, job_id
        )
        by_topology: dict = {}
        for topology, setup_groups in grouped.items():
            all_results = [r for results in setup_groups.values() for r in results]
            total = len(all_results)
            failed = sum(1 for r in all_results if r.status == data_service.TestStatusEnum.FAILED)
            passed = sum(1 for r in all_results if r.status == data_service.TestStatusEnum.PASSED)
            by_topology[topology] = {
                "total": total,
                "failed": failed,
                "passed": passed,
                "pass_rate": round(passed / total * 100, 1) if total else 0.0,
                "failing_tests": [
                    r.test_name for r in all_results
                    if r.status == data_service.TestStatusEnum.FAILED
                ],
            }
        return _to_serializable({"by_topology": by_topology})


@mcp.tool()
def search_failures_by_pattern(
    release: str,
    parent_job_id: str,
    error_pattern: str,
    module: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Full-text search on failure messages across a run.
    Answers "how many tests are failing with 'connection refused'?" or
    "find all tests with this specific traceback pattern."

    Returns: test_name, module, priority, status, failure_message snippet (500 chars),
    jenkins_topology. Sorted by priority then test name.
    """
    with get_db_context() as db:
        return _to_serializable(
            data_service.search_failure_messages(
                db, release, parent_job_id, error_pattern,
                module_filter=module, limit=limit,
            )
        )


@mcp.tool()
def get_module_health_summary(
    release: str,
    parent_job_id: str,
) -> list[dict]:
    """
    One-call comprehensive health overview across all modules in a run.
    Helps quickly identify the most problematic areas without multiple calls.

    Returns per-module: total, passed, failed, skipped, pass_rate,
    new_failure_count (vs previous run), flaky_count (was_rerun tests),
    bug_count (VLEI+VLENG bugs affecting skipped tests), p0_failures, p1_failures.
    Sorted alphabetically by module name.
    """
    with get_db_context() as db:
        return _to_serializable(
            data_service.get_module_health_for_run(db, release, parent_job_id)
        )


@mcp.tool()
def search_test_results(
    release: str,
    parent_job_id: str,
    test_name: str,
) -> list[dict]:
    """
    Search for a test by name (partial match) across all modules in a run.
    Use this to answer "why did test X fail?" without knowing the module or job_id.
    Returns status, module, priority, failure_message, jenkins_url, and job_id
    for every matching test result. Supports partial test name matching.
    """
    with get_db_context() as db:
        return data_service.search_test_by_name(db, release, parent_job_id, test_name)

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
                .order_by(TestResult.test_name)
                .all()
            )
            # If a test appears in multiple jobs, last row wins (order is stable via ORDER BY).
            return {
                r.test_name: {
                    "status": r.status.value if isinstance(r.status, enum.Enum) else str(r.status),
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
