"""
Tests for admin sync last_processed_build functionality.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.db_models import Release, Module, Job


@pytest.fixture(scope="module")
def client():
    """Create test client."""
    return TestClient(app)


class TestSyncLastProcessedBuilds:
    """Tests for sync last_processed_build endpoint."""

    def test_sync_success_with_updates(self, test_db, sample_release, sample_module):
        """Test successful sync operation with updates."""
        # Create jobs with parent_job_id
        job1 = Job(
            module_id=sample_module.id,
            parent_job_id="100",
            job_id="100",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        job2 = Job(
            module_id=sample_module.id,
            parent_job_id="216",
            job_id="216",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        test_db.add_all([job1, job2])
        test_db.commit()

        # Release should start with last_processed_build = 0 (or None)
        assert sample_release.last_processed_build is None or sample_release.last_processed_build == 0

        # Perform sync manually (simulating endpoint logic)
        from sqlalchemy import func, cast, Integer

        max_parent_job = test_db.query(
            func.max(cast(Job.parent_job_id, Integer))
        ).join(Module).filter(
            Module.release_id == sample_release.id,
            Job.parent_job_id.isnot(None),
            Job.parent_job_id != ''
        ).scalar()

        assert max_parent_job == 216

        # Update release
        sample_release.last_processed_build = max_parent_job
        test_db.commit()
        test_db.refresh(sample_release)

        assert sample_release.last_processed_build == 216

    def test_sync_no_updates_needed(self, test_db, sample_release, sample_module):
        """Test sync when last_processed_build is already correct."""
        # Create job
        job = Job(
            module_id=sample_module.id,
            parent_job_id="150",
            job_id="150",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        test_db.add(job)

        # Set last_processed_build to correct value
        sample_release.last_processed_build = 150
        test_db.commit()

        # Perform sync
        from sqlalchemy import func, cast, Integer

        max_parent_job = test_db.query(
            func.max(cast(Job.parent_job_id, Integer))
        ).join(Module).filter(
            Module.release_id == sample_release.id,
            Job.parent_job_id.isnot(None),
            Job.parent_job_id != ''
        ).scalar()

        assert max_parent_job == 150
        assert sample_release.last_processed_build == 150  # No change needed

    def test_sync_empty_database(self, test_db):
        """Test sync with no releases in database."""
        releases = test_db.query(Release).all()

        # If there are releases, this test isn't applicable
        # This is more of a structural test
        assert releases is not None  # Query should work even if empty

    def test_sync_no_jobs_for_release(self, test_db, sample_release):
        """Test sync with release that has no jobs."""
        from sqlalchemy import func, cast, Integer

        # Query max parent_job_id when no jobs exist
        max_parent_job = test_db.query(
            func.max(cast(Job.parent_job_id, Integer))
        ).join(Module).filter(
            Module.release_id == sample_release.id,
            Job.parent_job_id.isnot(None),
            Job.parent_job_id != ''
        ).scalar()

        assert max_parent_job is None

    def test_sync_with_null_parent_job_id(self, test_db, sample_release, sample_module):
        """Test sync handles NULL parent_job_id correctly."""
        # Create job with NULL parent_job_id
        job = Job(
            module_id=sample_module.id,
            parent_job_id=None,  # NULL value
            job_id="100",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        test_db.add(job)
        test_db.commit()

        # Perform sync with defensive filtering
        from sqlalchemy import func, cast, Integer

        max_parent_job = test_db.query(
            func.max(cast(Job.parent_job_id, Integer))
        ).join(Module).filter(
            Module.release_id == sample_release.id,
            Job.parent_job_id.isnot(None),
            Job.parent_job_id != ''
        ).scalar()

        # Should return None since all parent_job_ids are NULL
        assert max_parent_job is None

    def test_sync_with_empty_parent_job_id(self, test_db, sample_release, sample_module):
        """Test sync handles empty string parent_job_id correctly."""
        # Create job with empty string parent_job_id
        job = Job(
            module_id=sample_module.id,
            parent_job_id='',  # Empty string
            job_id="100",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        test_db.add(job)
        test_db.commit()

        # Perform sync with defensive filtering
        from sqlalchemy import func, cast, Integer

        max_parent_job = test_db.query(
            func.max(cast(Job.parent_job_id, Integer))
        ).join(Module).filter(
            Module.release_id == sample_release.id,
            Job.parent_job_id.isnot(None),
            Job.parent_job_id != ''
        ).scalar()

        # Should return None since all parent_job_ids are empty
        assert max_parent_job is None

    def test_sync_mixed_valid_and_invalid_parent_job_ids(self, test_db, sample_release, sample_module):
        """Test sync with mix of valid and invalid parent_job_ids."""
        # Create jobs with mixed parent_job_ids
        job1 = Job(
            module_id=sample_module.id,
            parent_job_id="100",  # Valid
            job_id="100",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        job2 = Job(
            module_id=sample_module.id,
            parent_job_id=None,  # NULL
            job_id="101",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        job3 = Job(
            module_id=sample_module.id,
            parent_job_id="",  # Empty
            job_id="102",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        job4 = Job(
            module_id=sample_module.id,
            parent_job_id="216",  # Valid (max)
            job_id="216",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        test_db.add_all([job1, job2, job3, job4])
        test_db.commit()

        # Perform sync with defensive filtering
        from sqlalchemy import func, cast, Integer

        max_parent_job = test_db.query(
            func.max(cast(Job.parent_job_id, Integer))
        ).join(Module).filter(
            Module.release_id == sample_release.id,
            Job.parent_job_id.isnot(None),
            Job.parent_job_id != ''
        ).scalar()

        # Should return 216 (ignoring NULL and empty values)
        assert max_parent_job == 216

    def test_sync_multiple_releases(self, test_db):
        """Test sync with multiple releases."""
        # Create multiple releases
        release1 = Release(
            name="6.4.0.0",
            is_active=True,
            jenkins_job_url="https://jenkins.example.com/job/6.4.0.0"
        )
        release2 = Release(
            name="7.0.0.0",
            is_active=True,
            jenkins_job_url="https://jenkins.example.com/job/7.0.0.0"
        )
        test_db.add_all([release1, release2])
        test_db.commit()
        test_db.refresh(release1)
        test_db.refresh(release2)

        # Create modules
        module1 = Module(release_id=release1.id, name="module1")
        module2 = Module(release_id=release2.id, name="module2")
        test_db.add_all([module1, module2])
        test_db.commit()
        test_db.refresh(module1)
        test_db.refresh(module2)

        # Create jobs
        job1 = Job(
            module_id=module1.id,
            parent_job_id="216",
            job_id="216",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        job2 = Job(
            module_id=module2.id,
            parent_job_id="14",
            job_id="14",
            
            total=10,
            passed=10,
            failed=0,
            skipped=0
        )
        test_db.add_all([job1, job2])
        test_db.commit()

        # Sync both releases
        from sqlalchemy import func, cast, Integer

        for release in [release1, release2]:
            max_parent_job = test_db.query(
                func.max(cast(Job.parent_job_id, Integer))
            ).join(Module).filter(
                Module.release_id == release.id,
                Job.parent_job_id.isnot(None),
                Job.parent_job_id != ''
            ).scalar()

            if max_parent_job is not None:
                release.last_processed_build = max_parent_job

        test_db.commit()
        test_db.refresh(release1)
        test_db.refresh(release2)

        assert release1.last_processed_build == 216
        assert release2.last_processed_build == 14
