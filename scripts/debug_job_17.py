
import sys
import os
from sqlalchemy import func
from sqlalchemy.orm import Session

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.db_models import Job, TestResult, Module

def debug_job(job_id_display):
    db: Session = SessionLocal()
    try:
        # Find the job (business_policy, job_id=17 presumably, or similar)
        # We'll search by job_id string
        jobs = db.query(Job).filter(Job.job_id == str(job_id_display)).all()
        
        print(f"Found {len(jobs)} jobs with ID {job_id_display}")
        
        for job in jobs:
            print(f"\n--- Job ID: {job.id} (Display ID: {job.job_id}) ---")
            print(f"Module: {job.module.name} (Release: {job.module.release.name})")
            print(f"Parent Job ID: {job.parent_job_id}")
            print(f"Job Table Stats -> Total: {job.total}, Passed: {job.passed}, Failed: {job.failed}, Skipped: {job.skipped}, NotRun: {job.not_run}")
            
            # DB Aggregation
            stats = db.query(
                TestResult.status,
                func.count(TestResult.id)
            ).filter(TestResult.job_id == job.id).group_by(TestResult.status).all()
            
            print("TestResult Table Stats:")
            total_rows = 0
            for status, count in stats:
                print(f"  {status}: {count}")
                total_rows += count
            print(f"  TOTAL ROWS: {total_rows}")
            
            # Check for duplicates (same test name)
            dupes = db.query(
                TestResult.test_name,
                func.count(TestResult.id)
            ).filter(TestResult.job_id == job.id)\
             .group_by(TestResult.file_path, TestResult.class_name, TestResult.test_name)\
             .having(func.count(TestResult.id) > 1).all()
             
            if dupes:
                print(f"WARNING: Found {len(dupes)} duplicate tests!")
                for name, count in dupes[:5]:
                    print(f"  {name}: {count} copies")
    finally:
        db.close()

if __name__ == "__main__":
    debug_job(17)
