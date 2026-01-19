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
from sqlalchemy import text
from sqlalchemy.orm import Session
import urllib3

from app.models.db_models import BugMetadata, BugTestcaseMapping

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class BugUpdaterService:
    """Service for updating bug tracking data from Jenkins."""

    JENKINS_URL = "https://jenkins2.vdev.sjc.aristanetworks.com/job/jira_centralize_repo/lastSuccessfulBuild/artifact/vlei_vleng_dict.json"

    def __init__(self, db: Session, jenkins_user: str, jenkins_token: str):
        """
        Initialize service.

        Args:
            db: Database session
            jenkins_user: Jenkins username
            jenkins_token: Jenkins API token
        """
        self.db = db
        self.auth = HTTPBasicAuth(jenkins_user, jenkins_token)

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

    def _download_json(self) -> Dict[str, List]:
        """Download vlei_vleng_dict.json from Jenkins."""
        logger.info(f"Downloading bug data from {self.JENKINS_URL}")

        response = requests.get(
            self.JENKINS_URL,
            auth=self.auth,
            timeout=30,
            verify=False  # Match existing JenkinsClient behavior
        )
        response.raise_for_status()

        data = response.json()
        logger.info(f"Downloaded {len(data.get('VLEI', []))} VLEI and "
                   f"{len(data.get('VLENG', []))} VLENG bugs")
        return data

    def _parse_bugs(self, json_data: Dict) -> Tuple[List[Dict], List[Dict]]:
        """
        Parse JSON into bug records and mapping records.

        Returns:
            (bugs_data, mappings_data) where:
            - bugs_data: List of dicts for bug_metadata table
            - mappings_data: List of dicts for bug_testcase_mappings table
        """
        bugs_data = []
        mappings_data = []

        for bug_type in ['VLEI', 'VLENG']:
            for bug in json_data.get(bug_type, []):
                # Parse bug metadata
                bug_record = {
                    'defect_id': bug['defect_id'],
                    'bug_type': bug_type,
                    'url': bug['URL'],
                    'labels': json.dumps(bug.get('labels', [])),
                    'status': bug.get('jira_info', {}).get('status'),
                    'summary': bug.get('jira_info', {}).get('summary'),
                    'priority': bug.get('jira_info', {}).get('priority'),
                    'assignee': bug.get('jira_info', {}).get('assignee'),
                    'component': bug.get('jira_info', {}).get('component'),
                    'resolution': bug.get('jira_info', {}).get('resolution'),
                    'affected_versions': bug.get('jira_info', {}).get('affected_versions'),
                }
                bugs_data.append(bug_record)

                # Parse case_id mappings (comma-separated)
                case_ids_str = bug.get('case_id', '')
                if case_ids_str:
                    case_ids = [cid.strip() for cid in case_ids_str.split(',')]
                    for case_id in case_ids:
                        if case_id:  # Skip empty strings
                            mappings_data.append({
                                'defect_id': bug['defect_id'],
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

        # 2. Build mapping records with bug_id lookup, deduplicating as we go
        mapping_records = []
        seen_mappings = set()  # Track unique (bug_id, case_id) pairs

        for mapping in mappings_data:
            # Get bug_id from defect_id
            bug = self.db.query(BugMetadata).filter(
                BugMetadata.defect_id == mapping['defect_id']
            ).first()

            if bug:
                mapping_key = (bug.id, mapping['case_id'])

                # Only add if we haven't seen this combination before
                if mapping_key not in seen_mappings:
                    seen_mappings.add(mapping_key)
                    mapping_records.append(
                        BugTestcaseMapping(
                            bug_id=bug.id,
                            case_id=mapping['case_id']
                        )
                    )

        # 3. Bulk insert
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
