import sys
import os
from sqlalchemy import func
from sqlalchemy.orm import Session

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.db_models import Job, TestResult, Module

def debug_module_view(release_name, module_name, parent_job_id):
    db: Session = SessionLocal()
    try:
        print(f"--- Debugging View for Module '{module_name}' in Run {parent_job_id} ({release_name}) ---")
        
        # 1. Find all jobs in this run that have ANY tests for this module
        # This matches `get_jobs_for_testcase_module` logic + parent_job_id filter
        job_ids_subquery = db.query(TestResult.job_id).distinct().filter(TestResult.testcase_module == module_name).subquery()

        jobs = db.query(Job).join(Module, Job.module_id == Module.id).filter(
                Module.release.has(name=release_name),
                Job.parent_job_id == parent_job_id,
                Job.id.in_(job_ids_subquery)
            ).all()
            
        print(f"Found {len(jobs)} contributing jobs:")
        
        grand_total = 0
        
        for job in jobs:
            print(f"\nJob {job.job_id} (Module: {job.module.name}):")
            
            # Count tests specifically for this testcase_module
            stats = db.query(
                TestResult.status,
                func.count(TestResult.id)
            ).filter(
                TestResult.job_id == job.id,
                TestResult.testcase_module == module_name
            ).group_by(TestResult.status).all()
            
            job_total = 0
            for status, count in stats:
                print(f"  {status}: {count}")
                job_total += count
            
            print(f"  -> Contribution to Total: {job_total}")
            grand_total += job_total
            
        print(f"\nGRAND TOTAL: {grand_total}")

    finally:
        db.close()

if __name__ == "__main__":
    debug_module_view("7.0", "business_policy", "33")