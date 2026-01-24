"""
Unit tests for parameterized test metadata matching.

Tests that parameterized test names (e.g., test_foo[param]) correctly match
metadata entries (e.g., test_foo) for priority and topology enrichment.
"""
import pytest

from app.models.db_models import TestcaseMetadata, TestResult, Job, Module, Release, TestStatusEnum
from app.utils.test_name_utils import normalize_test_name, extract_test_parameter, is_parameterized_test


class TestNormalizeTestName:
    """Test the normalize_test_name utility function."""

    def test_parameterized_test_single_param(self):
        """Test normalization of single parameter test."""
        assert normalize_test_name("test_foo[param]") == "test_foo"

    def test_parameterized_test_multiple_params(self):
        """Test normalization of multi-parameter test."""
        assert normalize_test_name("test_foo[1-True-xyz]") == "test_foo"

    def test_parameterized_test_topology(self):
        """Test normalization of topology parameter."""
        assert normalize_test_name("test_create_policy[5-site]") == "test_create_policy"

    def test_non_parameterized_test(self):
        """Test that non-parameterized tests remain unchanged."""
        assert normalize_test_name("test_bar") == "test_bar"

    def test_empty_parameters(self):
        """Test normalization of empty parameters."""
        assert normalize_test_name("test_foo[]") == "test_foo"

    def test_empty_string(self):
        """Test normalization of empty string."""
        assert normalize_test_name("") == ""

    def test_none_value(self):
        """Test normalization handles None (returns None)."""
        assert normalize_test_name(None) == None


class TestExtractTestParameter:
    """Test the extract_test_parameter utility function."""

    def test_single_parameter(self):
        """Test extraction of single parameter."""
        base, param = extract_test_parameter("test_foo[5-site]")
        assert base == "test_foo"
        assert param == "5-site"

    def test_numeric_parameter(self):
        """Test extraction of numeric parameter."""
        base, param = extract_test_parameter("test_foo[1]")
        assert base == "test_foo"
        assert param == "1"

    def test_no_parameter(self):
        """Test extraction when no parameter exists."""
        base, param = extract_test_parameter("test_bar")
        assert base == "test_bar"
        assert param is None


class TestIsParameterizedTest:
    """Test the is_parameterized_test utility function."""

    def test_parameterized(self):
        """Test detection of parameterized test."""
        assert is_parameterized_test("test_foo[param]") is True

    def test_non_parameterized(self):
        """Test detection of non-parameterized test."""
        assert is_parameterized_test("test_bar") is False

    def test_empty_string(self):
        """Test detection with empty string."""
        assert is_parameterized_test("") is False


class TestParameterizedMetadataMatching:
    """Test that parameterized tests correctly match metadata during import."""

    @pytest.fixture
    def db_with_metadata(self, test_db):
        """Create database with test metadata."""
        # Create release
        release = Release(name="7.0.0.0", is_active=True)
        test_db.add(release)

        # Create module
        module = Module(release_id=1, name="business_policy")
        test_db.add(module)

        # Create metadata for base test (without parameters)
        metadata = TestcaseMetadata(
            testcase_name="test_create_policy",
            priority="P0",
            topology="5-site",
            module="business_policy",
            test_state="PROD"
        )
        test_db.add(metadata)

        test_db.commit()
        return test_db

    def test_parameterized_test_gets_priority(self, db_with_metadata):
        """Test that parameterized test receives priority from metadata."""
        # Create job
        job = Job(
            module_id=1,
            job_id="123",
            jenkins_url="http://jenkins/job/test/123",
            version="7.0.0.0"
        )
        db_with_metadata.add(job)
        db_with_metadata.commit()

        # Create test result with parameterized name (simulating what parser creates)
        result = TestResult(
            job_id=job.id,
            file_path="data_plane/tests/business_policy/test_policy.py",
            class_name="TestPolicy",
            test_name="test_create_policy[5-site]",  # Parameterized!
            status=TestStatusEnum.PASSED,
            priority=None,  # Start with NULL
            setup_ip="10.1.1.1",
            jenkins_topology="5s"
        )
        db_with_metadata.add(result)
        db_with_metadata.commit()

        # Test normalization lookup (simulating what import_service does)
        from app.utils.test_name_utils import normalize_test_name
        normalized_name = normalize_test_name(result.test_name)

        # Query metadata using normalized name
        metadata = db_with_metadata.query(TestcaseMetadata).filter(
            TestcaseMetadata.testcase_name == normalized_name
        ).first()

        # Verify the match works
        assert metadata is not None, "Should find metadata using normalized name"
        assert metadata.priority == "P0"
        assert normalized_name == "test_create_policy", "Normalization should strip parameters"

        # Simulate the import service updating priority
        result.priority = metadata.priority
        db_with_metadata.commit()

        # Verify final state
        assert result.priority == "P0", "Parameterized test should inherit priority from base test metadata"
        assert result.test_name == "test_create_policy[5-site]", "Full test name should be preserved"

    def test_multiple_parameterized_variants(self, db_with_metadata):
        """Test that multiple parameterized variants all get same metadata."""
        # Create job
        job = Job(
            module_id=1,
            job_id="124",
            jenkins_url="http://jenkins/job/test/124",
            version="7.0.0.0"
        )
        db_with_metadata.add(job)
        db_with_metadata.commit()

        # Create multiple parameterized variants
        result1 = TestResult(
            job_id=job.id,
            file_path="data_plane/tests/business_policy/test_policy.py",
            class_name="TestPolicy",
            test_name="test_create_policy[5-site]",
            status=TestStatusEnum.PASSED,
            setup_ip="10.1.1.1",
            jenkins_topology="5s"
        )
        result2 = TestResult(
            job_id=job.id,
            file_path="data_plane/tests/business_policy/test_policy.py",
            class_name="TestPolicy",
            test_name="test_create_policy[3-site]",  # Different parameter
            status=TestStatusEnum.FAILED,
            setup_ip="10.1.1.2",
            jenkins_topology="3s"
        )
        db_with_metadata.add_all([result1, result2])
        db_with_metadata.commit()

        # Test that both variants normalize to same base name
        from app.utils.test_name_utils import normalize_test_name
        assert normalize_test_name(result1.test_name) == normalize_test_name(result2.test_name) == "test_create_policy"

        # Both should match the same metadata
        for result in [result1, result2]:
            normalized_name = normalize_test_name(result.test_name)
            metadata = db_with_metadata.query(TestcaseMetadata).filter(
                TestcaseMetadata.testcase_name == normalized_name
            ).first()
            assert metadata is not None
            result.priority = metadata.priority

        db_with_metadata.commit()

        # Verify both variants get same priority
        assert result1.priority == "P0"
        assert result2.priority == "P0", "All parameterized variants should inherit same priority"

    def test_non_parameterized_test_still_works(self, db_with_metadata):
        """Test that non-parameterized tests continue to work correctly."""
        # Add metadata for non-parameterized test
        metadata = TestcaseMetadata(
            testcase_name="test_simple",
            priority="P1",
            topology="3-site"
        )
        db_with_metadata.add(metadata)
        db_with_metadata.commit()

        # Create job
        job = Job(
            module_id=1,
            job_id="125",
            jenkins_url="http://jenkins/job/test/125",
            version="7.0.0.0"
        )
        db_with_metadata.add(job)
        db_with_metadata.commit()

        # Create non-parameterized test result
        result = TestResult(
            job_id=job.id,
            file_path="data_plane/tests/basic/test_simple.py",
            class_name="TestBasic",
            test_name="test_simple",  # No parameters
            status=TestStatusEnum.PASSED,
            setup_ip="10.1.1.1",
            jenkins_topology="3s"
        )
        db_with_metadata.add(result)
        db_with_metadata.commit()

        # Test normalization (should return same name)
        from app.utils.test_name_utils import normalize_test_name
        normalized_name = normalize_test_name(result.test_name)
        assert normalized_name == "test_simple"

        # Query metadata
        matched_metadata = db_with_metadata.query(TestcaseMetadata).filter(
            TestcaseMetadata.testcase_name == normalized_name
        ).first()

        # Verify non-parameterized test gets priority
        assert matched_metadata is not None
        result.priority = matched_metadata.priority
        db_with_metadata.commit()

        assert result.priority == "P1"

    def test_no_metadata_returns_null_priority(self, db_with_metadata):
        """Test that tests without metadata get NULL priority."""
        # Create job
        job = Job(
            module_id=1,
            job_id="126",
            jenkins_url="http://jenkins/job/test/126",
            version="7.0.0.0"
        )
        db_with_metadata.add(job)
        db_with_metadata.commit()

        # Create test result for which no metadata exists
        result = TestResult(
            job_id=job.id,
            file_path="data_plane/tests/unknown/test_unknown.py",
            class_name="TestUnknown",
            test_name="test_unknown[param]",
            status=TestStatusEnum.PASSED,
            setup_ip="10.1.1.1",
            jenkins_topology="5s"
        )
        db_with_metadata.add(result)
        db_with_metadata.commit()

        # Test normalization and lookup
        from app.utils.test_name_utils import normalize_test_name
        normalized_name = normalize_test_name(result.test_name)
        assert normalized_name == "test_unknown"

        # Try to find metadata (should not exist)
        matched_metadata = db_with_metadata.query(TestcaseMetadata).filter(
            TestcaseMetadata.testcase_name == normalized_name
        ).first()

        # Verify test without metadata has NULL priority
        assert matched_metadata is None, "No metadata should exist for this test"
        assert result.priority is None, "Test without metadata should have NULL priority"
