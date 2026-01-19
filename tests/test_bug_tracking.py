"""
Tests for bug tracking functionality.

Covers:
- BugUpdaterService (download, parse, upsert, mapping creation)
- Bug API endpoints (update, status)
- Bug data retrieval for test results
"""
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from pydantic import ValidationError
from sqlalchemy.orm import Session
from requests.exceptions import RequestException

from app.services.bug_updater_service import (
    BugUpdaterService,
    JenkinsBugData,
    JenkinsBugRecord,
    JiraBugInfo
)
from app.models.db_models import BugMetadata, BugTestcaseMapping, TestcaseMetadata, TestResult
from app.models.schemas import BugSchema
from app.services.data_service import get_bugs_for_tests


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def bug_service(test_db: Session):
    """Create BugUpdaterService instance for testing."""
    return BugUpdaterService(
        db=test_db,
        jenkins_user="test_user",
        jenkins_token="test_token",
        jenkins_bug_url="https://test.jenkins.com/bugs.json",
        verify_ssl=True
    )


@pytest.fixture
def sample_jenkins_json():
    """Sample Jenkins bug JSON data."""
    return {
        "VLEI": [
            {
                "defect_id": "VLEI-12345",
                "URL": "https://jira.example.com/browse/VLEI-12345",
                "labels": ["networking", "critical"],
                "case_id": "C12345,C12346",
                "jira_info": {
                    "status": "Open",
                    "summary": "Network connectivity issue",
                    "priority": "Critical",
                    "assignee": "john.doe@example.com",
                    "component": "Networking",
                    "resolution": None,
                    "affected_versions": "7.0.0.0"
                }
            },
            {
                "defect_id": "VLEI-12346",
                "URL": "https://jira.example.com/browse/VLEI-12346",
                "labels": ["routing"],
                "case_id": "C12347",
                "jira_info": {
                    "status": "Closed",
                    "summary": "BGP routing problem",
                    "priority": "High",
                    "assignee": "jane.smith@example.com",
                    "component": "Routing",
                    "resolution": "Fixed",
                    "affected_versions": "6.4.0.0"
                }
            }
        ],
        "VLENG": [
            {
                "defect_id": "VLENG-5678",
                "URL": "https://jira.example.com/browse/VLENG-5678",
                "labels": ["software"],
                "case_id": "C12348",
                "jira_info": {
                    "status": "In Progress",
                    "summary": "Software upgrade failure",
                    "priority": "Medium",
                    "assignee": "bob.johnson@example.com",
                    "component": "Software",
                    "resolution": None,
                    "affected_versions": "7.0.0.0"
                }
            }
        ]
    }


@pytest.fixture
def sample_validated_data(sample_jenkins_json):
    """Sample validated JenkinsBugData."""
    return JenkinsBugData.model_validate(sample_jenkins_json)


# ============================================================================
# BugUpdaterService Tests - JSON Validation
# ============================================================================

def test_jenkins_bug_data_validation_success(sample_jenkins_json):
    """Test that valid Jenkins JSON passes validation."""
    validated = JenkinsBugData.model_validate(sample_jenkins_json)
    assert len(validated.VLEI) == 2
    assert len(validated.VLENG) == 1
    assert validated.VLEI[0].defect_id == "VLEI-12345"
    assert validated.VLEI[0].jira_info.status == "Open"


def test_jenkins_bug_data_validation_missing_required_field():
    """Test that missing required fields raise ValidationError."""
    invalid_json = {
        "VLEI": [
            {
                # Missing defect_id
                "URL": "https://jira.example.com/browse/VLEI-12345"
            }
        ]
    }
    with pytest.raises(ValidationError):
        JenkinsBugData.model_validate(invalid_json)


def test_jenkins_bug_data_validation_empty_lists():
    """Test that empty VLEI/VLENG lists are handled correctly."""
    empty_json = {"VLEI": [], "VLENG": []}
    validated = JenkinsBugData.model_validate(empty_json)
    assert len(validated.VLEI) == 0
    assert len(validated.VLENG) == 0


def test_jenkins_bug_data_validation_optional_jira_info():
    """Test that missing jira_info is handled correctly."""
    json_without_jira = {
        "VLEI": [
            {
                "defect_id": "VLEI-99999",
                "URL": "https://jira.example.com/browse/VLEI-99999",
                "case_id": "C99999"
            }
        ]
    }
    validated = JenkinsBugData.model_validate(json_without_jira)
    assert validated.VLEI[0].jira_info is None


def test_jenkins_bug_data_validation_null_case_id():
    """Test that null/None case_id is handled correctly."""
    json_with_null_case_id = {
        "VLEI": [
            {
                "defect_id": "VLEI-88888",
                "URL": "https://jira.example.com/browse/VLEI-88888",
                "case_id": None  # null in JSON
            }
        ]
    }
    validated = JenkinsBugData.model_validate(json_with_null_case_id)
    assert validated.VLEI[0].case_id is None


# ============================================================================
# BugUpdaterService Tests - Download
# ============================================================================

@patch('app.services.bug_updater_service.requests.get')
def test_download_json_success(mock_get, bug_service, sample_jenkins_json):
    """Test successful JSON download from Jenkins."""
    mock_response = Mock()
    mock_response.json.return_value = sample_jenkins_json
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    result = bug_service._download_json()

    assert isinstance(result, JenkinsBugData)
    assert len(result.VLEI) == 2
    assert len(result.VLENG) == 1
    mock_get.assert_called_once_with(
        "https://test.jenkins.com/bugs.json",
        auth=bug_service.auth,
        timeout=30,
        verify=True
    )


@patch('app.services.bug_updater_service.requests.get')
def test_download_json_ssl_warning(mock_get, test_db, sample_jenkins_json, caplog):
    """Test that SSL warning is logged when verify_ssl=False."""
    bug_service = BugUpdaterService(
        db=test_db,
        jenkins_user="test",
        jenkins_token="test",
        jenkins_bug_url="https://test.com/bugs.json",
        verify_ssl=False
    )

    mock_response = Mock()
    mock_response.json.return_value = sample_jenkins_json
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    bug_service._download_json()

    assert "SSL verification is disabled" in caplog.text


@patch('app.services.bug_updater_service.requests.get')
def test_download_json_network_error(mock_get, bug_service):
    """Test handling of network errors during download."""
    mock_get.side_effect = RequestException("Network error")

    with pytest.raises(RequestException):
        bug_service._download_json()


@patch('app.services.bug_updater_service.requests.get')
def test_download_json_validation_error(mock_get, bug_service):
    """Test handling of invalid JSON structure."""
    mock_response = Mock()
    # Missing required 'defect_id' field will cause validation error
    mock_response.json.return_value = {
        "VLEI": [
            {
                "URL": "https://test.com",  # Missing defect_id
                "labels": []
            }
        ]
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    with pytest.raises(ValidationError):
        bug_service._download_json()


# ============================================================================
# BugUpdaterService Tests - Parse
# ============================================================================

def test_parse_bugs_success(bug_service, sample_validated_data):
    """Test parsing of validated bug data into database records."""
    bugs_data, mappings_data = bug_service._parse_bugs(sample_validated_data)

    assert len(bugs_data) == 3  # 2 VLEI + 1 VLENG
    assert len(mappings_data) == 4  # C12345, C12346, C12347, C12348

    # Check first VLEI bug
    bug1 = bugs_data[0]
    assert bug1['defect_id'] == "VLEI-12345"
    assert bug1['bug_type'] == "VLEI"
    assert bug1['status'] == "Open"
    assert bug1['priority'] == "Critical"
    assert json.loads(bug1['labels']) == ["networking", "critical"]

    # Check mappings for first bug (comma-separated case_ids)
    vlei_mappings = [m for m in mappings_data if m['defect_id'] == 'VLEI-12345']
    assert len(vlei_mappings) == 2
    assert {'defect_id': 'VLEI-12345', 'case_id': 'C12345'} in vlei_mappings
    assert {'defect_id': 'VLEI-12345', 'case_id': 'C12346'} in vlei_mappings


def test_parse_bugs_with_empty_case_id(bug_service):
    """Test parsing bugs with empty case_id field."""
    data = JenkinsBugData(
        VLEI=[
            JenkinsBugRecord(
                defect_id="VLEI-99999",
                URL="https://jira.com/VLEI-99999",
                case_id=""  # Empty case_id
            )
        ]
    )

    bugs_data, mappings_data = bug_service._parse_bugs(data)

    assert len(bugs_data) == 1
    assert len(mappings_data) == 0  # No mappings created for empty case_id


def test_parse_bugs_with_null_case_id(bug_service):
    """Test parsing bugs with null/None case_id field."""
    data = JenkinsBugData(
        VLEI=[
            JenkinsBugRecord(
                defect_id="VLEI-88888",
                URL="https://jira.com/VLEI-88888",
                case_id=None  # None case_id (from Jenkins JSON)
            )
        ]
    )

    bugs_data, mappings_data = bug_service._parse_bugs(data)

    assert len(bugs_data) == 1
    assert len(mappings_data) == 0  # No mappings created for None case_id


def test_parse_bugs_without_jira_info(bug_service):
    """Test parsing bugs without jira_info."""
    data = JenkinsBugData(
        VLEI=[
            JenkinsBugRecord(
                defect_id="VLEI-99999",
                URL="https://jira.com/VLEI-99999",
                case_id="C99999",
                jira_info=None
            )
        ]
    )

    bugs_data, mappings_data = bug_service._parse_bugs(data)

    bug = bugs_data[0]
    assert bug['status'] is None
    assert bug['priority'] is None
    assert bug['assignee'] is None


# ============================================================================
# BugUpdaterService Tests - Upsert
# ============================================================================

def test_upsert_bugs_insert_new(bug_service, test_db):
    """Test inserting new bugs."""
    bugs_data = [
        {
            'defect_id': 'VLEI-TEST-1',
            'bug_type': 'VLEI',
            'url': 'https://jira.com/VLEI-TEST-1',
            'status': 'Open',
            'summary': 'Test bug',
            'priority': 'High',
            'assignee': 'test@example.com',
            'component': 'Test',
            'resolution': None,
            'affected_versions': '1.0.0',
            'labels': json.dumps(['test'])
        }
    ]

    stats = bug_service._upsert_bugs(bugs_data)

    assert stats['total'] == 1
    assert stats['vlei'] == 1
    assert stats['vleng'] == 0

    # Verify bug was inserted
    bug = test_db.query(BugMetadata).filter_by(defect_id='VLEI-TEST-1').first()
    assert bug is not None
    assert bug.status == 'Open'
    assert bug.priority == 'High'


def test_upsert_bugs_update_existing(bug_service, test_db):
    """Test updating existing bugs."""
    # Insert initial bug
    initial_bug = BugMetadata(
        defect_id='VLEI-TEST-2',
        bug_type='VLEI',
        url='https://jira.com/VLEI-TEST-2',
        status='Open',
        priority='Low'
    )
    test_db.add(initial_bug)
    test_db.commit()

    # Update with new status
    bugs_data = [
        {
            'defect_id': 'VLEI-TEST-2',
            'bug_type': 'VLEI',
            'url': 'https://jira.com/VLEI-TEST-2',
            'status': 'Closed',
            'summary': 'Updated summary',
            'priority': 'High',
            'assignee': None,
            'component': None,
            'resolution': 'Fixed',
            'affected_versions': None,
            'labels': json.dumps([])
        }
    ]

    bug_service._upsert_bugs(bugs_data)

    # Verify bug was updated
    bug = test_db.query(BugMetadata).filter_by(defect_id='VLEI-TEST-2').first()
    assert bug.status == 'Closed'
    assert bug.priority == 'High'
    assert bug.resolution == 'Fixed'


def test_upsert_bugs_empty_list(bug_service):
    """Test upserting empty bug list."""
    stats = bug_service._upsert_bugs([])
    assert stats == {'total': 0, 'vlei': 0, 'vleng': 0}


# ============================================================================
# BugUpdaterService Tests - Mapping Creation (with N+1 fix)
# ============================================================================

def test_recreate_mappings_success(bug_service, test_db):
    """Test creating bug-testcase mappings with deduplication."""
    # Create bugs first
    bug1 = BugMetadata(defect_id='VLEI-MAP-1', bug_type='VLEI', url='http://test.com/1')
    bug2 = BugMetadata(defect_id='VLEI-MAP-2', bug_type='VLEI', url='http://test.com/2')
    test_db.add_all([bug1, bug2])
    test_db.commit()

    mappings_data = [
        {'defect_id': 'VLEI-MAP-1', 'case_id': 'C100'},
        {'defect_id': 'VLEI-MAP-1', 'case_id': 'C101'},
        {'defect_id': 'VLEI-MAP-2', 'case_id': 'C102'},
        # Duplicate - should be deduplicated
        {'defect_id': 'VLEI-MAP-1', 'case_id': 'C100'},
    ]

    count = bug_service._recreate_mappings(mappings_data)

    assert count == 3  # 4 input, 1 duplicate removed
    mappings = test_db.query(BugTestcaseMapping).all()
    assert len(mappings) == 3

    # Verify unique constraint is maintained
    case_ids = [m.case_id for m in mappings]
    assert 'C100' in case_ids
    assert 'C101' in case_ids
    assert 'C102' in case_ids


def test_recreate_mappings_deletes_old_mappings(bug_service, test_db):
    """Test that old mappings are deleted before creating new ones."""
    # Create bug and old mapping
    bug = BugMetadata(defect_id='VLEI-DEL-1', bug_type='VLEI', url='http://test.com')
    test_db.add(bug)
    test_db.commit()

    old_mapping = BugTestcaseMapping(bug_id=bug.id, case_id='C_OLD')
    test_db.add(old_mapping)
    test_db.commit()

    assert test_db.query(BugTestcaseMapping).count() == 1

    # Recreate with new mappings
    mappings_data = [
        {'defect_id': 'VLEI-DEL-1', 'case_id': 'C_NEW'}
    ]
    bug_service._recreate_mappings(mappings_data)

    # Old mapping should be deleted, new one created
    mappings = test_db.query(BugTestcaseMapping).all()
    assert len(mappings) == 1
    assert mappings[0].case_id == 'C_NEW'


def test_recreate_mappings_skips_unknown_bugs(bug_service, test_db):
    """Test that mappings for non-existent bugs are skipped."""
    mappings_data = [
        {'defect_id': 'VLEI-NONEXISTENT', 'case_id': 'C999'}
    ]

    count = bug_service._recreate_mappings(mappings_data)

    assert count == 0
    assert test_db.query(BugTestcaseMapping).count() == 0


def test_recreate_mappings_empty_list(bug_service):
    """Test recreating mappings with empty list."""
    count = bug_service._recreate_mappings([])
    assert count == 0


# ============================================================================
# BugUpdaterService Tests - Full Update Flow
# ============================================================================

@patch('app.services.bug_updater_service.requests.get')
def test_update_bug_mappings_full_flow(mock_get, bug_service, test_db, sample_jenkins_json):
    """Test complete bug update flow from download to database."""
    mock_response = Mock()
    mock_response.json.return_value = sample_jenkins_json
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    stats = bug_service.update_bug_mappings()

    assert stats['bugs_updated'] == 3
    assert stats['vlei_count'] == 2
    assert stats['vleng_count'] == 1
    assert stats['mappings_created'] > 0

    # Verify bugs were created
    bugs = test_db.query(BugMetadata).all()
    assert len(bugs) == 3

    # Verify mappings were created
    mappings = test_db.query(BugTestcaseMapping).all()
    assert len(mappings) > 0


@patch('app.services.bug_updater_service.requests.get')
def test_update_bug_mappings_rollback_on_error(mock_get, bug_service, test_db):
    """Test that database changes are rolled back on error."""
    mock_get.side_effect = RequestException("Network error")

    initial_bug_count = test_db.query(BugMetadata).count()

    with pytest.raises(RequestException):
        bug_service.update_bug_mappings()

    # Verify no changes were committed
    assert test_db.query(BugMetadata).count() == initial_bug_count


# ============================================================================
# BugUpdaterService Tests - Helper Methods
# ============================================================================

def test_get_last_update_time(bug_service, test_db):
    """Test retrieving last update timestamp."""
    # Initially should be None
    assert bug_service.get_last_update_time() is None

    # Add bug with timestamp
    bug = BugMetadata(
        defect_id='VLEI-TIME-1',
        bug_type='VLEI',
        url='http://test.com',
        updated_at=datetime(2024, 1, 15, 10, 30, 0)
    )
    test_db.add(bug)
    test_db.commit()

    last_update = bug_service.get_last_update_time()
    assert last_update == datetime(2024, 1, 15, 10, 30, 0)


def test_get_bug_counts(bug_service, test_db):
    """Test retrieving bug counts by type."""
    # Initially should be zero
    counts = bug_service.get_bug_counts()
    assert counts == {'total': 0, 'vlei': 0, 'vleng': 0}

    # Add bugs
    test_db.add_all([
        BugMetadata(defect_id='VLEI-1', bug_type='VLEI', url='http://test.com/1'),
        BugMetadata(defect_id='VLEI-2', bug_type='VLEI', url='http://test.com/2'),
        BugMetadata(defect_id='VLENG-1', bug_type='VLENG', url='http://test.com/3'),
    ])
    test_db.commit()

    counts = bug_service.get_bug_counts()
    assert counts == {'total': 3, 'vlei': 2, 'vleng': 1}


# ============================================================================
# Data Service Tests - get_bugs_for_tests
# ============================================================================

def test_get_bugs_for_tests_success(test_db):
    """Test retrieving bugs for test results."""
    # Create testcase metadata
    metadata = TestcaseMetadata(
        testcase_name='test_network_connectivity',
        test_case_id='C12345',
        priority='P0'
    )
    test_db.add(metadata)
    test_db.commit()

    # Create bug and mapping
    bug = BugMetadata(
        defect_id='VLEI-NET-1',
        bug_type='VLEI',
        url='http://test.com',
        status='Open',
        priority='Critical',
        summary='Network issue'
    )
    test_db.add(bug)
    test_db.commit()

    mapping = BugTestcaseMapping(bug_id=bug.id, case_id='C12345')
    test_db.add(mapping)
    test_db.commit()

    # Create test result
    test_result = TestResult(
        test_key='test_network_connectivity_key',
        test_name='test_network_connectivity',
        status='FAILED'
    )

    # Get bugs for test
    bugs_by_test = get_bugs_for_tests(test_db, [test_result])

    assert 'test_network_connectivity_key' in bugs_by_test
    assert len(bugs_by_test['test_network_connectivity_key']) == 1
    assert bugs_by_test['test_network_connectivity_key'][0].defect_id == 'VLEI-NET-1'


def test_get_bugs_for_tests_multiple_bugs(test_db):
    """Test retrieving multiple bugs for a single test."""
    metadata = TestcaseMetadata(
        testcase_name='test_routing',
        test_case_id='C99999',
        priority='P1'
    )
    test_db.add(metadata)
    test_db.commit()

    # Create multiple bugs
    bug1 = BugMetadata(defect_id='VLEI-R1', bug_type='VLEI', url='http://test.com/1')
    bug2 = BugMetadata(defect_id='VLEI-R2', bug_type='VLEI', url='http://test.com/2')
    test_db.add_all([bug1, bug2])
    test_db.commit()

    # Map both bugs to same test case
    test_db.add_all([
        BugTestcaseMapping(bug_id=bug1.id, case_id='C99999'),
        BugTestcaseMapping(bug_id=bug2.id, case_id='C99999')
    ])
    test_db.commit()

    test_result = TestResult(test_key='routing_key', test_name='test_routing', status='FAILED')
    bugs_by_test = get_bugs_for_tests(test_db, [test_result])

    assert len(bugs_by_test['routing_key']) == 2


def test_get_bugs_for_tests_no_bugs(test_db):
    """Test that empty dict is returned when no bugs exist."""
    test_result = TestResult(test_key='key', test_name='test_no_bugs', status='PASSED')
    bugs_by_test = get_bugs_for_tests(test_db, [test_result])
    assert bugs_by_test == {}


def test_get_bugs_for_tests_empty_list(test_db):
    """Test handling of empty test results list."""
    bugs_by_test = get_bugs_for_tests(test_db, [])
    assert bugs_by_test == {}


def test_get_bugs_for_tests_null_bug_handling(test_db):
    """Test that None bugs are skipped gracefully."""
    # This test verifies the null check we added
    metadata = TestcaseMetadata(
        testcase_name='test_null_check',
        test_case_id='C_NULL',
        priority='P2'
    )
    test_db.add(metadata)
    test_db.commit()

    test_result = TestResult(test_key='null_key', test_name='test_null_check', status='FAILED')

    # Should not raise error even if no bugs exist
    bugs_by_test = get_bugs_for_tests(test_db, [test_result])
    assert bugs_by_test == {}
