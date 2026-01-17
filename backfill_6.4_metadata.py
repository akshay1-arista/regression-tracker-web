#!/usr/bin/env python3
"""
Backfill metadata for release 6.4 jobs.

Updates version, parent_job_id, and jenkins_url for all jobs in release 6.4.
"""

import sys
import sqlite3
from pathlib import Path

# Configuration
DATABASE_PATH = "data/regression_tracker.db"
RELEASE = "6.4"
VERSION = "6.4.2.0"
PARENT_JOB_ID = "216"
PARENT_JOB_URL = "https://jenkins2.vdev.sjc.aristanetworks.com/job/QA_Release_6.4/job/SILVER/job/DATA_PLANE/job/MODULE-RUN-ESXI-IPV4-ALL/216/"
JENKINS_JOB_URL = "https://jenkins2.vdev.sjc.aristanetworks.com/job/QA_Release_6.4/job/SILVER/job/DATA_PLANE/job/MODULE-RUN-ESXI-IPV4-ALL/"  # Main job URL (without build number)


def backfill_metadata():
    """Backfill metadata for 6.4 jobs."""

    # Connect to database
    db_path = Path(DATABASE_PATH)
    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        print(f"🔍 Finding jobs for release {RELEASE}...")

        # Get all jobs for release 6.4
        cursor.execute("""
            SELECT j.id, j.job_id, m.name as module_name, j.version, j.parent_job_id, j.jenkins_url
            FROM jobs j
            JOIN modules m ON j.module_id = m.id
            JOIN releases r ON m.release_id = r.id
            WHERE r.name = ?
        """, (RELEASE,))

        jobs = cursor.fetchall()

        if not jobs:
            print(f"⚠️  No jobs found for release {RELEASE}")
            return False

        print(f"📊 Found {len(jobs)} jobs to update")
        print()

        # Show current state
        print("Current state (first 5 jobs):")
        print("-" * 100)
        print(f"{'Module':<25} {'Job ID':<10} {'Version':<15} {'Parent ID':<12} {'Jenkins URL'}")
        print("-" * 100)
        for job in jobs[:5]:
            print(f"{job['module_name']:<25} {job['job_id']:<10} {job['version'] or 'NULL':<15} {job['parent_job_id'] or 'NULL':<12} {job['jenkins_url'] or 'NULL'}")
        if len(jobs) > 5:
            print(f"... and {len(jobs) - 5} more jobs")
        print()

        # Check if release jenkins_job_url needs updating
        cursor.execute("SELECT jenkins_job_url FROM releases WHERE name = ?", (RELEASE,))
        release_row = cursor.fetchone()
        needs_release_update = not release_row or not release_row['jenkins_job_url']

        # Confirm update
        print(f"Will update all {len(jobs)} jobs with:")
        print(f"  • version = '{VERSION}'")
        print(f"  • parent_job_id = '{PARENT_JOB_ID}'")
        print(f"  • jenkins_url = '{PARENT_JOB_URL}' (parent job reference)")
        print()
        if needs_release_update:
            print(f"Will also update release jenkins_job_url:")
            print(f"  • jenkins_job_url = '{JENKINS_JOB_URL}'")
            print()

        response = input("Proceed with update? [y/N]: ").strip().lower()
        if response != 'y':
            print("❌ Update cancelled")
            return False

        # Update jobs
        print()
        print("🔄 Updating jobs...")

        cursor.execute("""
            UPDATE jobs
            SET version = ?,
                parent_job_id = ?,
                jenkins_url = ?
            WHERE id IN (
                SELECT j.id
                FROM jobs j
                JOIN modules m ON j.module_id = m.id
                JOIN releases r ON m.release_id = r.id
                WHERE r.name = ?
            )
        """, (VERSION, PARENT_JOB_ID, PARENT_JOB_URL, RELEASE))

        updated_count = cursor.rowcount
        print(f"✅ Successfully updated {updated_count} jobs")

        # Update release jenkins_job_url if needed
        if needs_release_update:
            print()
            print("🔄 Updating release jenkins_job_url...")
            cursor.execute("""
                UPDATE releases
                SET jenkins_job_url = ?
                WHERE name = ?
            """, (JENKINS_JOB_URL, RELEASE))
            print(f"✅ Successfully updated release jenkins_job_url")

        conn.commit()
        print()

        # Verify updates
        print("Verification (first 5 jobs):")
        print("-" * 100)
        cursor.execute("""
            SELECT j.id, j.job_id, m.name as module_name, j.version, j.parent_job_id, j.jenkins_url
            FROM jobs j
            JOIN modules m ON j.module_id = m.id
            JOIN releases r ON m.release_id = r.id
            WHERE r.name = ?
            ORDER BY m.name
            LIMIT 5
        """, (RELEASE,))

        verified_jobs = cursor.fetchall()
        print(f"{'Module':<25} {'Job ID':<10} {'Version':<15} {'Parent ID':<12} {'Jenkins URL'}")
        print("-" * 100)
        for job in verified_jobs:
            jenkins_url_display = job['jenkins_url'][:60] + "..." if job['jenkins_url'] and len(job['jenkins_url']) > 60 else job['jenkins_url']
            print(f"{job['module_name']:<25} {job['job_id']:<10} {job['version']:<15} {job['parent_job_id']:<12} {jenkins_url_display}")
        print()

        print("🎉 Backfill completed successfully!")
        print()
        print("Next steps:")
        print("  1. Refresh your dashboard at http://localhost:8000/")
        print("  2. Select release '6.4'")
        print("  3. Select version '6.4.2.0'")
        print("  4. Your modules should now appear in the dropdown!")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


if __name__ == "__main__":
    success = backfill_metadata()
    sys.exit(0 if success else 1)
