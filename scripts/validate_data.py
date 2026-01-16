#!/usr/bin/env python3
"""
Data Validation Script for Regression Tracker Web Application.

This script validates data integrity and verifies that calculations match
expected results. It can be used to compare the web application's data
processing with a CLI tool or previous implementation.

Usage:
    python scripts/validate_data.py [--verbose] [--export-report]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

# Add app to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.db import Release, Module, Job, Build, TestCase, TestResult
from sqlalchemy import func, distinct


class DataValidator:
    """Validates data integrity and calculations in the database."""

    def __init__(self, verbose: bool = False):
        """Initialize validator."""
        self.verbose = verbose
        self.db = SessionLocal()
        self.errors = []
        self.warnings = []
        self.stats = {}

    def log(self, message: str, level: str = "INFO"):
        """Log a message."""
        if self.verbose or level != "INFO":
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {level}: {message}")

    def add_error(self, test: str, message: str):
        """Add an error to the results."""
        self.errors.append({"test": test, "message": message})
        self.log(f"ERROR in {test}: {message}", "ERROR")

    def add_warning(self, test: str, message: str):
        """Add a warning to the results."""
        self.warnings.append({"test": test, "message": message})
        self.log(f"WARNING in {test}: {message}", "WARN")

    def validate_data_integrity(self) -> bool:
        """Validate basic data integrity constraints."""
        self.log("Validating data integrity...")
        passed = True

        # Test 1: Check for orphaned modules (modules without a release)
        orphaned_modules = self.db.query(Module).filter(
            ~Module.release_id.in_(self.db.query(Release.id))
        ).count()
        if orphaned_modules > 0:
            self.add_error("orphaned_modules", f"Found {orphaned_modules} modules without a valid release")
            passed = False

        # Test 2: Check for orphaned jobs (jobs without a module)
        orphaned_jobs = self.db.query(Job).filter(
            ~Job.module_id.in_(self.db.query(Module.id))
        ).count()
        if orphaned_jobs > 0:
            self.add_error("orphaned_jobs", f"Found {orphaned_jobs} jobs without a valid module")
            passed = False

        # Test 3: Check for orphaned builds (builds without a job)
        orphaned_builds = self.db.query(Build).filter(
            ~Build.job_id.in_(self.db.query(Job.id))
        ).count()
        if orphaned_builds > 0:
            self.add_error("orphaned_builds", f"Found {orphaned_builds} builds without a valid job")
            passed = False

        # Test 4: Check for orphaned test results (results without a build)
        orphaned_results = self.db.query(TestResult).filter(
            ~TestResult.build_id.in_(self.db.query(Build.id))
        ).count()
        if orphaned_results > 0:
            self.add_error("orphaned_results", f"Found {orphaned_results} test results without a valid build")
            passed = False

        # Test 5: Check for duplicate releases
        duplicate_releases = self.db.query(
            Release.name, func.count(Release.id).label('count')
        ).group_by(Release.name).having(func.count(Release.id) > 1).all()
        if duplicate_releases:
            self.add_warning("duplicate_releases", f"Found {len(duplicate_releases)} duplicate release names")

        # Test 6: Check for builds with invalid build numbers
        invalid_builds = self.db.query(Build).filter(Build.build_number < 1).count()
        if invalid_builds > 0:
            self.add_error("invalid_build_numbers", f"Found {invalid_builds} builds with invalid build numbers")
            passed = False

        self.log(f"Data integrity validation {'PASSED' if passed else 'FAILED'}")
        return passed

    def validate_calculations(self) -> bool:
        """Validate that statistical calculations are correct."""
        self.log("Validating calculations...")
        passed = True

        # Sample 10 random builds and verify their statistics
        sample_builds = self.db.query(Build).order_by(func.random()).limit(10).all()

        for build in sample_builds:
            # Get test results for this build
            results = self.db.query(TestResult).filter(TestResult.build_id == build.id).all()

            # Calculate expected values
            expected_total = len(results)
            expected_passed = sum(1 for r in results if r.status == 'PASSED')
            expected_failed = sum(1 for r in results if r.status == 'FAILED')
            expected_skipped = sum(1 for r in results if r.status == 'SKIPPED')

            # Verify totals
            if build.total_tests != expected_total:
                self.add_error(
                    f"build_{build.id}_total",
                    f"Build {build.id}: total_tests is {build.total_tests}, expected {expected_total}"
                )
                passed = False

            if build.passed_tests != expected_passed:
                self.add_error(
                    f"build_{build.id}_passed",
                    f"Build {build.id}: passed_tests is {build.passed_tests}, expected {expected_passed}"
                )
                passed = False

            if build.failed_tests != expected_failed:
                self.add_error(
                    f"build_{build.id}_failed",
                    f"Build {build.id}: failed_tests is {build.failed_tests}, expected {expected_failed}"
                )
                passed = False

            if build.skipped_tests != expected_skipped:
                self.add_error(
                    f"build_{build.id}_skipped",
                    f"Build {build.id}: skipped_tests is {build.skipped_tests}, expected {expected_skipped}"
                )
                passed = False

        self.log(f"Calculation validation {'PASSED' if passed else 'FAILED'}")
        return passed

    def validate_consistency(self) -> bool:
        """Validate data consistency rules."""
        self.log("Validating consistency...")
        passed = True

        # Test 1: Verify job parent-child relationships are valid
        jobs_with_invalid_parents = self.db.query(Job).filter(
            Job.parent_job_id.isnot(None),
            ~Job.parent_job_id.in_(self.db.query(Job.id))
        ).count()
        if jobs_with_invalid_parents > 0:
            self.add_error(
                "invalid_parent_jobs",
                f"Found {jobs_with_invalid_parents} jobs with invalid parent_job_id"
            )
            passed = False

        # Test 2: Verify builds have reasonable timestamps
        future_builds = self.db.query(Build).filter(
            Build.timestamp > datetime.now()
        ).count()
        if future_builds > 0:
            self.add_warning("future_builds", f"Found {future_builds} builds with future timestamps")

        # Test 3: Verify test case uniqueness within builds
        duplicate_tests = self.db.query(
            TestResult.build_id,
            TestResult.test_case_id,
            func.count(TestResult.id).label('count')
        ).group_by(
            TestResult.build_id,
            TestResult.test_case_id
        ).having(func.count(TestResult.id) > 1).all()

        if duplicate_tests:
            self.add_error(
                "duplicate_test_results",
                f"Found {len(duplicate_tests)} duplicate test results in builds"
            )
            passed = False

        self.log(f"Consistency validation {'PASSED' if passed else 'FAILED'}")
        return passed

    def collect_statistics(self):
        """Collect database statistics."""
        self.log("Collecting statistics...")

        self.stats = {
            "releases": self.db.query(Release).count(),
            "modules": self.db.query(Module).count(),
            "jobs": self.db.query(Job).count(),
            "builds": self.db.query(Build).count(),
            "test_cases": self.db.query(TestCase).count(),
            "test_results": self.db.query(TestResult).count(),
            "unique_test_cases": self.db.query(distinct(TestCase.name)).count(),
            "avg_tests_per_build": self.db.query(func.avg(Build.total_tests)).scalar() or 0,
            "avg_pass_rate": self.db.query(
                func.avg(
                    func.cast(Build.passed_tests, float) * 100.0 /
                    func.nullif(Build.total_tests, 0)
                )
            ).scalar() or 0,
        }

        if self.verbose:
            print("\nDatabase Statistics:")
            print("=" * 50)
            for key, value in self.stats.items():
                if isinstance(value, float):
                    print(f"  {key}: {value:.2f}")
                else:
                    print(f"  {key}: {value}")
            print("=" * 50)

    def run_all_validations(self) -> bool:
        """Run all validation tests."""
        print("\n" + "=" * 60)
        print("  Regression Tracker - Data Validation")
        print("=" * 60 + "\n")

        self.collect_statistics()

        tests = [
            self.validate_data_integrity,
            self.validate_calculations,
            self.validate_consistency,
        ]

        results = [test() for test in tests]
        all_passed = all(results)

        return all_passed

    def generate_report(self) -> Dict[str, Any]:
        """Generate a validation report."""
        return {
            "timestamp": datetime.now().isoformat(),
            "stats": self.stats,
            "errors": self.errors,
            "warnings": self.warnings,
            "passed": len(self.errors) == 0,
            "total_tests": sum(1 for _ in self.errors) + sum(1 for _ in self.warnings),
        }

    def export_report(self, filepath: Path):
        """Export validation report to JSON file."""
        report = self.generate_report()
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)
        self.log(f"Report exported to {filepath}")

    def close(self):
        """Close database connection."""
        self.db.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate data integrity in Regression Tracker database"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "-r", "--export-report",
        metavar="FILE",
        help="Export validation report to JSON file"
    )

    args = parser.parse_args()

    validator = DataValidator(verbose=args.verbose)

    try:
        all_passed = validator.run_all_validations()

        # Print summary
        print("\n" + "=" * 60)
        print("  Validation Summary")
        print("=" * 60)
        print(f"  Errors:   {len(validator.errors)}")
        print(f"  Warnings: {len(validator.warnings)}")
        print(f"  Status:   {'✓ PASSED' if all_passed else '✗ FAILED'}")
        print("=" * 60 + "\n")

        # Export report if requested
        if args.export_report:
            validator.export_report(Path(args.export_report))

        # Return appropriate exit code
        sys.exit(0 if all_passed else 1)

    finally:
        validator.close()


if __name__ == "__main__":
    main()
