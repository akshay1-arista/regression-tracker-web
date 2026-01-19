"""
Bug Updater Service - Downloads and updates VLEI/VLENG bug mappings.

Responsibilities:
- Download vlei_vleng_dict.json from Jenkins
- Parse JSON into bug metadata and mappings
- UPSERT bug_metadata table
- Recreate bug_testcase_mappings
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import requests
from requests.auth import HTTPBasicAuth
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session
import urllib3

from app.models.db_models import BugMetadata, BugTestcaseMapping

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


# Pydantic schemas for validating Jenkins JSON data
class JiraBugInfo(BaseModel):
    """Jira bug information embedded in Jenkins JSON."""
    status: Optional[str] = None
    summary: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    component: Optional[str] = None
    resolution: Optional[str] = None
    affected_versions: Optional[str] = None


class JenkinsBugRecord(BaseModel):
    """Individual bug record from Jenkins JSON."""
    defect_id: str
    URL: str
    labels: List[str] = Field(default_factory=list)
    case_id: str = ""
    jira_info: Optional[JiraBugInfo] = None


class JenkinsBugData(BaseModel):
    """Root structure of Jenkins bug JSON."""
    VLEI: List[JenkinsBugRecord] = Field(default_factory=list)
    VLENG: List[JenkinsBugRecord] = Field(default_factory=list)


class BugUpdaterService:
    """Service for updating bug tracking data from Jenkins."""

    def __init__(self, db: Session, jenkins_user: str, jenkins_token: str,
                 jenkins_bug_url: str, verify_ssl: bool = True):
        """
        Initialize service.

        Args:
            db: Database session
            jenkins_user: Jenkins username
            jenkins_token: Jenkins API token
            jenkins_bug_url: URL to Jenkins bug data JSON
            verify_ssl: Whether to verify SSL certificates (default: True)
        """
        self.db = db
        self.auth = HTTPBasicAuth(jenkins_user, jenkins_token)
        self.jenkins_bug_url = jenkins_bug_url
        self.verify_ssl = verify_ssl

    def update_bug_mappings(self) -> Dict[str, int]:
        """
        Main entry point - download and update bug mappings.

        Returns:
            Statistics dict: {
                'bugs_updated': int,
                'vlei_count': int,
                'vleng_count': int,
                'mappings_created': int
            }
        """
        logger.info("Starting bug mappings update...")

        try:
            # 1. Download JSON
            json_data = self._download_json()

            # 2. Parse into bug records and mappings
            bugs_data, mappings_data = self._parse_bugs(json_data)

            # 3. UPSERT bug metadata
            bug_stats = self._upsert_bugs(bugs_data)

            # 4. Recreate mappings
            mappings_count = self._recreate_mappings(mappings_data)

            self.db.commit()

            stats = {
                'bugs_updated': bug_stats['total'],
                'vlei_count': bug_stats['vlei'],
                'vleng_count': bug_stats['vleng'],
                'mappings_created': mappings_count
            }

            logger.info(f"Bug update complete: {stats}")
            return stats

        except Exception as e:
            self.db.rollback()
            logger.error(f"Bug update failed: {e}", exc_info=True)
            raise

    def _download_json(self) -> JenkinsBugData:
        """
        Download and validate vlei_vleng_dict.json from Jenkins.

        Returns:
            Validated JenkinsBugData object

        Raises:
            ValidationError: If JSON structure doesn't match expected schema
            requests.RequestException: If download fails
        """
        logger.info(f"Downloading bug data from {self.jenkins_bug_url}")

        if not self.verify_ssl:
            logger.warning("SSL verification is disabled for Jenkins bug data download - "
                          "connection is vulnerable to MITM attacks")

        response = requests.get(
            self.jenkins_bug_url,
            auth=self.auth,
            timeout=30,
            verify=self.verify_ssl
        )
        response.raise_for_status()

        raw_data = response.json()

        # Validate JSON structure using Pydantic
        try:
            validated_data = JenkinsBugData.model_validate(raw_data)
            logger.info(f"Downloaded and validated {len(validated_data.VLEI)} VLEI and "
                       f"{len(validated_data.VLENG)} VLENG bugs")
            return validated_data
        except ValidationError as e:
            logger.error(f"Jenkins JSON validation failed: {e}")
            raise

    def _parse_bugs(self, json_data: JenkinsBugData) -> Tuple[List[Dict], List[Dict]]:
        """
        Parse validated JSON data into bug records and mapping records.

        Args:
            json_data: Validated JenkinsBugData object

        Returns:
            (bugs_data, mappings_data) where:
            - bugs_data: List of dicts for bug_metadata table
            - mappings_data: List of dicts for bug_testcase_mappings table
        """
        bugs_data = []
        mappings_data = []

        for bug_type, bug_list in [('VLEI', json_data.VLEI), ('VLENG', json_data.VLENG)]:
            for bug in bug_list:
                # Parse bug metadata from validated Pydantic model
                bug_record = {
                    'defect_id': bug.defect_id,
                    'bug_type': bug_type,
                    'url': bug.URL,
                    'labels': json.dumps(bug.labels),
                    'status': bug.jira_info.status if bug.jira_info else None,
                    'summary': bug.jira_info.summary if bug.jira_info else None,
                    'priority': bug.jira_info.priority if bug.jira_info else None,
                    'assignee': bug.jira_info.assignee if bug.jira_info else None,
                    'component': bug.jira_info.component if bug.jira_info else None,
                    'resolution': bug.jira_info.resolution if bug.jira_info else None,
                    'affected_versions': bug.jira_info.affected_versions if bug.jira_info else None,
                }
                bugs_data.append(bug_record)

                # Parse case_id mappings (comma-separated)
                if bug.case_id:
                    case_ids = [cid.strip() for cid in bug.case_id.split(',')]
                    for case_id in case_ids:
                        if case_id:  # Skip empty strings
                            mappings_data.append({
                                'defect_id': bug.defect_id,
                                'case_id': case_id
                            })

        logger.info(f"Parsed {len(bugs_data)} bugs and {len(mappings_data)} mappings")
        return bugs_data, mappings_data

    def _upsert_bugs(self, bugs_data: List[Dict]) -> Dict[str, int]:
        """
        UPSERT bug_metadata table using INSERT ... ON CONFLICT.

        Returns:
            Stats dict: {'total': int, 'vlei': int, 'vleng': int}
        """
        if not bugs_data:
            return {'total': 0, 'vlei': 0, 'vleng': 0}

        # SQLite UPSERT syntax
        upsert_sql = text("""
            INSERT INTO bug_metadata
                (defect_id, bug_type, url, status, summary, priority,
                 assignee, component, resolution, affected_versions, labels, updated_at)
            VALUES
                (:defect_id, :bug_type, :url, :status, :summary, :priority,
                 :assignee, :component, :resolution, :affected_versions, :labels, CURRENT_TIMESTAMP)
            ON CONFLICT(defect_id) DO UPDATE SET
                bug_type = excluded.bug_type,
                url = excluded.url,
                status = excluded.status,
                summary = excluded.summary,
                priority = excluded.priority,
                assignee = excluded.assignee,
                component = excluded.component,
                resolution = excluded.resolution,
                affected_versions = excluded.affected_versions,
                labels = excluded.labels,
                updated_at = CURRENT_TIMESTAMP
        """)

        for bug in bugs_data:
            self.db.execute(upsert_sql, bug)

        vlei_count = sum(1 for b in bugs_data if b['bug_type'] == 'VLEI')
        vleng_count = sum(1 for b in bugs_data if b['bug_type'] == 'VLENG')

        return {
            'total': len(bugs_data),
            'vlei': vlei_count,
            'vleng': vleng_count
        }

    def _recreate_mappings(self, mappings_data: List[Dict]) -> int:
        """
        Recreate bug_testcase_mappings table.

        Strategy: Delete all existing mappings, insert new ones.
        This ensures no stale mappings if bugs are reassigned.

        Returns:
            Number of mappings created
        """
        if not mappings_data:
            return 0

        # 1. Delete all existing mappings
        self.db.query(BugTestcaseMapping).delete()

        # 2. Build defect_id -> bug_id lookup dictionary (single query instead of N queries)
        defect_ids = list(set(m['defect_id'] for m in mappings_data))
        bugs = self.db.query(BugMetadata).filter(
            BugMetadata.defect_id.in_(defect_ids)
        ).all()
        bug_id_map = {bug.defect_id: bug.id for bug in bugs}

        # 3. Build mapping records using lookup map, deduplicating as we go
        mapping_records = []
        seen_mappings = set()  # Track unique (bug_id, case_id) pairs

        for mapping in mappings_data:
            bug_id = bug_id_map.get(mapping['defect_id'])

            if bug_id:
                mapping_key = (bug_id, mapping['case_id'])

                # Only add if we haven't seen this combination before
                if mapping_key not in seen_mappings:
                    seen_mappings.add(mapping_key)
                    mapping_records.append(
                        BugTestcaseMapping(
                            bug_id=bug_id,
                            case_id=mapping['case_id']
                        )
                    )

        # 4. Bulk insert
        self.db.bulk_save_objects(mapping_records)

        logger.info(f"Created {len(mapping_records)} bug-testcase mappings "
                   f"(deduplicated from {len(mappings_data)} total)")
        return len(mapping_records)

    def get_last_update_time(self) -> Optional[datetime]:
        """Get the most recent bug update timestamp."""
        result = self.db.query(BugMetadata.updated_at)\
            .order_by(BugMetadata.updated_at.desc())\
            .first()
        return result[0] if result else None

    def get_bug_counts(self) -> Dict[str, int]:
        """Get bug counts by type."""
        vlei_count = self.db.query(BugMetadata)\
            .filter(BugMetadata.bug_type == 'VLEI').count()
        vleng_count = self.db.query(BugMetadata)\
            .filter(BugMetadata.bug_type == 'VLENG').count()

        return {
            'total': vlei_count + vleng_count,
            'vlei': vlei_count,
            'vleng': vleng_count
        }
