"""
Tests for environment (prod/staging) feature.

Covers:
- determine_environment() logic
- _apply_environment_filter() validation
- Environment filtering in data_service queries
- get_build_parameters() parsing
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.jenkins_service import determine_environment
from app.services.data_service import _apply_environment_filter, VALID_ENVIRONMENTS
from app.models.db_models import Job, Module, Release


class TestDetermineEnvironment:
    """Tests for determine_environment() function."""

    def test_staging_true_string(self):
        """RUN_STAGING_TESTS_ONLY='true' returns staging."""
        assert determine_environment({'RUN_STAGING_TESTS_ONLY': 'true'}) == 'staging'

    def test_staging_true_uppercase(self):
        """RUN_STAGING_TESTS_ONLY='True' returns staging."""
        assert determine_environment({'RUN_STAGING_TESTS_ONLY': 'True'}) == 'staging'

    def test_staging_true_bool(self):
        """RUN_STAGING_TESTS_ONLY=True (bool) returns staging."""
        assert determine_environment({'RUN_STAGING_TESTS_ONLY': True}) == 'staging'

    def test_prod_false_string(self):
        """RUN_STAGING_TESTS_ONLY='false' returns prod."""
        assert determine_environment({'RUN_STAGING_TESTS_ONLY': 'false'}) == 'prod'

    def test_prod_false_bool(self):
        """RUN_STAGING_TESTS_ONLY=False (bool) returns prod."""
        assert determine_environment({'RUN_STAGING_TESTS_ONLY': False}) == 'prod'

    def test_prod_missing_key(self):
        """Missing RUN_STAGING_TESTS_ONLY defaults to prod."""
        assert determine_environment({}) == 'prod'

    def test_prod_empty_params(self):
        """Empty params dict defaults to prod."""
        assert determine_environment({}) == 'prod'

    def test_prod_other_value(self):
        """Non-true value defaults to prod."""
        assert determine_environment({'RUN_STAGING_TESTS_ONLY': 'yes'}) == 'prod'

    def test_other_params_ignored(self):
        """Other parameters don't affect environment detection."""
        assert determine_environment({
            'SOME_OTHER_PARAM': 'true',
            'RUN_STAGING_TESTS_ONLY': 'false'
        }) == 'prod'


class TestApplyEnvironmentFilter:
    """Tests for _apply_environment_filter() function."""

    def test_none_returns_query_unchanged(self, test_db):
        """None environment returns query without filter."""
        query = test_db.query(Job)
        result = _apply_environment_filter(query, None)
        # Should be the same query object
        assert result is query

    def test_prod_applies_filter(self, test_db):
        """'prod' applies Job.environment filter."""
        query = test_db.query(Job)
        result = _apply_environment_filter(query, 'prod')
        # Should be a different query (filter applied)
        assert result is not query

    def test_staging_applies_filter(self, test_db):
        """'staging' applies Job.environment filter."""
        query = test_db.query(Job)
        result = _apply_environment_filter(query, 'staging')
        assert result is not query

    def test_invalid_environment_raises(self, test_db):
        """Invalid environment raises ValueError."""
        query = test_db.query(Job)
        with pytest.raises(ValueError, match="Invalid environment"):
            _apply_environment_filter(query, 'development')

    def test_invalid_environment_empty_string(self, test_db):
        """Empty string is falsy, so returns query unchanged."""
        query = test_db.query(Job)
        result = _apply_environment_filter(query, '')
        assert result is query

    def test_valid_environments_constant(self):
        """VALID_ENVIRONMENTS contains expected values."""
        assert VALID_ENVIRONMENTS == {'prod', 'staging'}


class TestEnvironmentFiltering:
    """Tests for environment filtering in data_service queries."""

    @pytest.fixture
    def env_data(self, test_db):
        """Create prod and staging jobs for testing."""
        release = Release(
            name="7.0",
            is_active=True,
            jenkins_job_url="https://jenkins.example.com/job/7.0"
        )
        test_db.add(release)
        test_db.flush()

        module = Module(release_id=release.id, name="business_policy")
        test_db.add(module)
        test_db.flush()

        prod_job = Job(
            module_id=module.id,
            job_id="100",
            total=10, passed=8, failed=1, skipped=1, pass_rate=80.0,
            environment='prod',
            parent_job_id='50',
            version='7.0.0.0'
        )
        staging_job = Job(
            module_id=module.id,
            job_id="101",
            total=5, passed=3, failed=1, skipped=1, pass_rate=60.0,
            environment='staging',
            parent_job_id='51',
            version='7.0.0.0'
        )
        test_db.add_all([prod_job, staging_job])
        test_db.commit()

        return {
            'release': release,
            'module': module,
            'prod_job': prod_job,
            'staging_job': staging_job
        }

    def test_get_jobs_for_module_no_filter(self, test_db, env_data):
        """Without environment filter, both jobs returned."""
        from app.services.data_service import get_jobs_for_module
        jobs = get_jobs_for_module(test_db, "7.0", "business_policy")
        assert len(jobs) == 2

    def test_get_jobs_for_module_prod_filter(self, test_db, env_data):
        """With prod filter, only prod job returned."""
        from app.services.data_service import get_jobs_for_module
        jobs = get_jobs_for_module(test_db, "7.0", "business_policy", environment='prod')
        assert len(jobs) == 1
        assert jobs[0].environment == 'prod'

    def test_get_jobs_for_module_staging_filter(self, test_db, env_data):
        """With staging filter, only staging job returned."""
        from app.services.data_service import get_jobs_for_module
        jobs = get_jobs_for_module(test_db, "7.0", "business_policy", environment='staging')
        assert len(jobs) == 1
        assert jobs[0].environment == 'staging'

    def test_get_latest_parent_job_ids_prod(self, test_db, env_data):
        """Latest parent job IDs filtered by prod environment."""
        from app.services.data_service import get_latest_parent_job_ids
        parent_ids = get_latest_parent_job_ids(test_db, "7.0", environment='prod')
        assert '50' in parent_ids
        assert '51' not in parent_ids

    def test_get_latest_parent_job_ids_staging(self, test_db, env_data):
        """Latest parent job IDs filtered by staging environment."""
        from app.services.data_service import get_latest_parent_job_ids
        parent_ids = get_latest_parent_job_ids(test_db, "7.0", environment='staging')
        assert '51' in parent_ids
        assert '50' not in parent_ids

    def test_get_jobs_by_parent_job_id_with_environment(self, test_db, env_data):
        """get_jobs_by_parent_job_id respects environment filter."""
        from app.services.data_service import get_jobs_by_parent_job_id
        # Without filter — should find the job
        jobs = get_jobs_by_parent_job_id(test_db, "7.0", "50")
        assert len(jobs) == 1

        # With matching environment
        jobs = get_jobs_by_parent_job_id(test_db, "7.0", "50", environment='prod')
        assert len(jobs) == 1

        # With non-matching environment
        jobs = get_jobs_by_parent_job_id(test_db, "7.0", "50", environment='staging')
        assert len(jobs) == 0


class TestGetBuildParameters:
    """Tests for JenkinsClient.get_build_parameters()."""

    def test_parse_parameters(self):
        """Correctly parses build parameters from Jenkins API response."""
        from app.services.jenkins_service import JenkinsClient

        mock_response = MagicMock()
        mock_response.json.return_value = {
            'actions': [
                {
                    'parameters': [
                        {'name': 'RUN_STAGING_TESTS_ONLY', 'value': 'true'},
                        {'name': 'VERSION', 'value': '7.0.0.0'}
                    ]
                },
                {}  # Action without parameters
            ]
        }

        client = JenkinsClient.__new__(JenkinsClient)
        client._make_request = MagicMock(return_value=mock_response)

        params = client.get_build_parameters('https://jenkins.example.com/job/test/1/')
        assert params == {
            'RUN_STAGING_TESTS_ONLY': 'true',
            'VERSION': '7.0.0.0'
        }

    def test_empty_actions(self):
        """Returns empty dict when no actions present."""
        from app.services.jenkins_service import JenkinsClient

        mock_response = MagicMock()
        mock_response.json.return_value = {'actions': []}

        client = JenkinsClient.__new__(JenkinsClient)
        client._make_request = MagicMock(return_value=mock_response)

        params = client.get_build_parameters('https://jenkins.example.com/job/test/1/')
        assert params == {}

    def test_request_failure_returns_empty(self):
        """Returns empty dict on request failure."""
        from app.services.jenkins_service import JenkinsClient

        client = JenkinsClient.__new__(JenkinsClient)
        client._make_request = MagicMock(side_effect=Exception("Connection error"))

        params = client.get_build_parameters('https://jenkins.example.com/job/test/1/')
        assert params == {}

    def test_none_value_parameter(self):
        """Parameters with None value are included."""
        from app.services.jenkins_service import JenkinsClient

        mock_response = MagicMock()
        mock_response.json.return_value = {
            'actions': [
                {
                    'parameters': [
                        {'name': 'PARAM1', 'value': None}
                    ]
                }
            ]
        }

        client = JenkinsClient.__new__(JenkinsClient)
        client._make_request = MagicMock(return_value=mock_response)

        params = client.get_build_parameters('https://jenkins.example.com/job/test/1/')
        assert params == {'PARAM1': None}


class TestJobEnvironmentDefault:
    """Tests for Job model environment default."""

    def test_job_default_environment(self, test_db):
        """Job defaults to 'prod' environment."""
        release = Release(name="test_rel", is_active=True)
        test_db.add(release)
        test_db.flush()

        module = Module(release_id=release.id, name="test_mod")
        test_db.add(module)
        test_db.flush()

        job = Job(
            module_id=module.id,
            job_id="1",
            total=0, passed=0, failed=0, skipped=0, pass_rate=0.0
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        assert job.environment == 'prod'

    def test_job_staging_environment(self, test_db):
        """Job can be created with 'staging' environment."""
        release = Release(name="test_rel2", is_active=True)
        test_db.add(release)
        test_db.flush()

        module = Module(release_id=release.id, name="test_mod2")
        test_db.add(module)
        test_db.flush()

        job = Job(
            module_id=module.id,
            job_id="2",
            total=0, passed=0, failed=0, skipped=0, pass_rate=0.0,
            environment='staging'
        )
        test_db.add(job)
        test_db.commit()
        test_db.refresh(job)

        assert job.environment == 'staging'
