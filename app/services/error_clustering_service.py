"""
Error Clustering Service

This module provides clustering functionality for test failure messages.
It groups similar errors together to help identify common root causes.

Algorithm:
1. Extract error signatures (error type, file path, line number, normalized message)
2. Cluster by exact fingerprint match (hash of signature)
3. Apply fuzzy matching for remaining failures (80% similarity threshold)
4. Return clusters sorted by size (count descending)
"""

import re
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from datetime import datetime
from difflib import SequenceMatcher
from collections import defaultdict

@dataclass
class ErrorSignature:
    """
    Structured representation of an error message signature.

    Attributes:
        error_type: Type of error (AssertionError, IndexError, etc.)
        file_path: Source file path where error occurred
        line_number: Line number where error occurred
        normalized_message: Error message with variables replaced by placeholders
        fingerprint: Hash of signature for exact matching
    """
    error_type: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    normalized_message: str = ""
    fingerprint: str = ""

    def __post_init__(self):
        """Generate fingerprint after initialization."""
        if not self.fingerprint:
            self.fingerprint = self._generate_fingerprint()

    def _generate_fingerprint(self) -> str:
        """Generate hash fingerprint for exact matching."""
        signature_parts = [
            self.error_type,
            self.file_path or "",
            str(self.line_number or ""),
            self.normalized_message
        ]
        signature_string = "|".join(signature_parts)
        return hashlib.md5(signature_string.encode()).hexdigest()


@dataclass
class ErrorCluster:
    """
    Group of test failures with similar error signatures.

    Attributes:
        signature: Common error signature for this cluster
        test_results: List of test result objects in this cluster
        count: Number of tests in cluster
        affected_topologies: Set of topologies where failures occurred
        affected_priorities: Set of test priorities in cluster
        first_seen: Timestamp of first occurrence
        sample_message: Full original error message (for display)
        match_type: 'exact' or 'fuzzy' matching strategy used
    """
    signature: ErrorSignature
    test_results: List = field(default_factory=list)
    count: int = 0
    affected_topologies: Set[str] = field(default_factory=set)
    affected_priorities: Set[str] = field(default_factory=set)
    first_seen: Optional[datetime] = None
    sample_message: str = ""
    match_type: str = "exact"

    def add_test_result(self, test_result):
        """Add a test result to this cluster."""
        self.test_results.append(test_result)
        self.count = len(self.test_results)

        # Track affected topologies and priorities
        # Use topology_metadata or jenkins_topology (TestResult has both, not 'topology')
        topology = None
        if hasattr(test_result, 'topology_metadata') and test_result.topology_metadata:
            topology = test_result.topology_metadata
        elif hasattr(test_result, 'jenkins_topology') and test_result.jenkins_topology:
            topology = test_result.jenkins_topology

        if topology:
            self.affected_topologies.add(topology)

        if hasattr(test_result, 'priority') and test_result.priority:
            self.affected_priorities.add(test_result.priority)

        # Set first_seen and sample_message if this is the first test
        if not self.sample_message and hasattr(test_result, 'failure_message'):
            self.sample_message = test_result.failure_message or ""
            if hasattr(test_result, 'created_at'):
                self.first_seen = test_result.created_at


@dataclass
class ClusterSummary:
    """
    Summary statistics for error clustering results.

    Attributes:
        total_failures: Total number of failed tests analyzed
        unique_clusters: Number of distinct error patterns found
        largest_cluster: Size of the largest cluster
        unclustered: Number of failures that couldn't be clustered
        clusters: List of error clusters
    """
    total_failures: int = 0
    unique_clusters: int = 0
    largest_cluster: int = 0
    unclustered: int = 0
    clusters: List[ErrorCluster] = field(default_factory=list)


def normalize_message(message: str) -> str:
    """
    Replace variable values with placeholders to group similar errors.

    Normalization Rules:
    - Numeric values: "Expected 200 but got 404" → "Expected {N} but got {N}"
    - IP addresses: "10.10.10.1" → "{IP}"
    - UUIDs/IDs: "edge-12345" → "edge-{ID}"
    - Hex addresses: "0x7f8a9b" → "{HEX}"
    - File paths: Strip absolute paths, keep relative paths

    Args:
        message: Original error message

    Returns:
        Normalized message with placeholders
    """
    if not message:
        return ""

    normalized = message

    # Replace hex memory addresses (0x...)
    normalized = re.sub(r'0x[0-9a-fA-F]+', '{HEX}', normalized)

    # Replace IP addresses (IPv4)
    normalized = re.sub(
        r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        '{IP}',
        normalized
    )

    # Replace UUIDs and long IDs
    normalized = re.sub(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        '{UUID}',
        normalized,
        flags=re.IGNORECASE
    )

    # Replace device/edge IDs (edge-12345, device-987)
    normalized = re.sub(r'(edge|device|node|host)-\d+', r'\1-{ID}', normalized, flags=re.IGNORECASE)

    # Replace standalone numbers (but preserve error codes and line numbers in context)
    # Match numbers not preceded/followed by letters or colons
    normalized = re.sub(r'(?<![a-zA-Z:\d])(\d+)(?![a-zA-Z:\d])', '{N}', normalized)

    # Replace absolute file paths, keep relative paths
    # Match paths like /home/user/... or C:\Users\...
    normalized = re.sub(
        r'(?:[A-Za-z]:\\|/)(?:[\w\-]+[\\/])*[\w\-\.]+',
        '{PATH}',
        normalized
    )

    # Normalize whitespace
    normalized = ' '.join(normalized.split())

    return normalized


def extract_error_signature(failure_message: str) -> ErrorSignature:
    """
    Parse failure message and extract structured signature.

    Extracts:
    - Error type (first line before colon)
    - File path and line number (from stack trace)
    - Normalized error message

    Args:
        failure_message: Full error message from JUnit XML

    Returns:
        ErrorSignature object with extracted fields
    """
    if not failure_message:
        return ErrorSignature(
            error_type="Unknown",
            normalized_message=""
        )

    lines = failure_message.strip().split('\n')

    # Extract error type from first line (before first colon)
    error_type = "Unknown"
    first_line = lines[0].strip()

    # Match patterns like "AssertionError: message" or "IndexError: pop from empty list"
    error_match = re.match(r'^([A-Za-z][A-Za-z0-9]*(?:Error|Exception|Warning)?)\s*:', first_line)
    if error_match:
        error_type = error_match.group(1)
    elif first_line:
        # If no colon, use first word as error type
        error_type = first_line.split()[0] if first_line.split() else "Unknown"

    # Extract file path and line number from stack trace
    # Look for patterns like:
    # - "File "path/to/file.py", line 123"
    # - "  File "path/to/file.py", line 123, in function_name"
    file_path = None
    line_number = None

    for line in lines:
        file_match = re.search(r'File\s+"([^"]+)",\s+line\s+(\d+)', line)
        if file_match:
            file_path = file_match.group(1)
            line_number = int(file_match.group(2))
            # Use the first file match (closest to error)
            break

    # Extract and normalize the error message
    # For AssertionError, try to get the assertion message
    normalized_message = ""

    if error_type == "AssertionError" and len(lines) > 0:
        # Get the assertion message (usually on first line after "AssertionError:")
        assertion_match = re.search(r'AssertionError:\s*(.+)', first_line)
        if assertion_match:
            normalized_message = normalize_message(assertion_match.group(1))
        elif len(lines) > 1:
            # Sometimes assertion message is on second line
            normalized_message = normalize_message(lines[1].strip())
    else:
        # For other errors, use the first line
        if ':' in first_line:
            message_part = first_line.split(':', 1)[1].strip()
            normalized_message = normalize_message(message_part)
        else:
            normalized_message = normalize_message(first_line)

    return ErrorSignature(
        error_type=error_type,
        file_path=file_path,
        line_number=line_number,
        normalized_message=normalized_message
    )


def calculate_similarity(sig1: ErrorSignature, sig2: ErrorSignature) -> float:
    """
    Calculate similarity score between two error signatures.

    Uses difflib.SequenceMatcher for fuzzy string matching.
    Considers both normalized message and error type.

    Args:
        sig1: First error signature
        sig2: Second error signature

    Returns:
        Similarity score between 0.0 and 1.0
    """
    # Must be same error type for fuzzy matching
    if sig1.error_type != sig2.error_type:
        return 0.0

    # Calculate message similarity
    matcher = SequenceMatcher(
        None,
        sig1.normalized_message,
        sig2.normalized_message
    )

    return matcher.ratio()


def cluster_failures(failures: List) -> ClusterSummary:
    """
    Group failures by error signature using hybrid clustering approach.

    Algorithm:
    1. Extract signatures for all failures
    2. Group by fingerprint (exact match)
    3. Apply fuzzy matching to remaining failures (80% similarity)
    4. Sort clusters by count descending

    Args:
        failures: List of TestResult objects with failure_message attribute

    Returns:
        ClusterSummary with all clusters and statistics
    """
    if not failures:
        return ClusterSummary()

    # Step 1: Extract signatures
    failure_signatures = []
    for failure in failures:
        if not hasattr(failure, 'failure_message'):
            continue

        signature = extract_error_signature(failure.failure_message or "")
        failure_signatures.append((failure, signature))

    # Step 2: Group by exact fingerprint
    fingerprint_clusters: Dict[str, ErrorCluster] = {}

    for failure, signature in failure_signatures:
        fingerprint = signature.fingerprint

        if fingerprint not in fingerprint_clusters:
            fingerprint_clusters[fingerprint] = ErrorCluster(
                signature=signature,
                match_type="exact"
            )

        fingerprint_clusters[fingerprint].add_test_result(failure)

    # Step 3: Fuzzy matching for small clusters (size = 1)
    # Group these "singleton" clusters by similarity
    singleton_clusters = [
        cluster for cluster in fingerprint_clusters.values()
        if cluster.count == 1
    ]

    multi_clusters = [
        cluster for cluster in fingerprint_clusters.values()
        if cluster.count > 1
    ]

    # Apply fuzzy matching to singletons
    fuzzy_clusters: List[ErrorCluster] = []
    used_indices: Set[int] = set()

    for i, cluster1 in enumerate(singleton_clusters):
        if i in used_indices:
            continue

        # Start a new fuzzy cluster
        fuzzy_cluster = ErrorCluster(
            signature=cluster1.signature,
            match_type="fuzzy"
        )
        fuzzy_cluster.add_test_result(cluster1.test_results[0])
        used_indices.add(i)

        # Find similar singletons
        for j, cluster2 in enumerate(singleton_clusters):
            if j <= i or j in used_indices:
                continue

            similarity = calculate_similarity(cluster1.signature, cluster2.signature)

            if similarity >= 0.80:  # 80% similarity threshold
                fuzzy_cluster.add_test_result(cluster2.test_results[0])
                used_indices.add(j)

        fuzzy_clusters.append(fuzzy_cluster)

    # Combine exact and fuzzy clusters
    all_clusters = multi_clusters + fuzzy_clusters

    # Sort by count descending
    all_clusters.sort(key=lambda c: c.count, reverse=True)

    # Calculate summary statistics
    total_failures = len(failures)
    unique_clusters = len(all_clusters)
    largest_cluster = max((c.count for c in all_clusters), default=0)
    unclustered = sum(1 for c in all_clusters if c.count == 1)

    return ClusterSummary(
        total_failures=total_failures,
        unique_clusters=unique_clusters,
        largest_cluster=largest_cluster,
        unclustered=unclustered,
        clusters=all_clusters
    )


def get_cluster_statistics(cluster_summary: ClusterSummary) -> Dict:
    """
    Calculate detailed statistics for dashboard display.

    Args:
        cluster_summary: ClusterSummary object

    Returns:
        Dictionary with cluster statistics
    """
    if not cluster_summary.clusters:
        return {
            "total_failures": 0,
            "unique_clusters": 0,
            "largest_cluster": 0,
            "average_cluster_size": 0.0,
            "unclustered": 0,
            "error_type_distribution": {},
            "match_type_distribution": {"exact": 0, "fuzzy": 0}
        }

    # Error type distribution
    error_type_counts = defaultdict(int)
    for cluster in cluster_summary.clusters:
        error_type_counts[cluster.signature.error_type] += cluster.count

    # Match type distribution
    match_type_counts = {"exact": 0, "fuzzy": 0}
    for cluster in cluster_summary.clusters:
        match_type_counts[cluster.match_type] += 1

    # Average cluster size (excluding singletons)
    multi_clusters = [c for c in cluster_summary.clusters if c.count > 1]
    avg_cluster_size = (
        sum(c.count for c in multi_clusters) / len(multi_clusters)
        if multi_clusters else 0.0
    )

    return {
        "total_failures": cluster_summary.total_failures,
        "unique_clusters": cluster_summary.unique_clusters,
        "largest_cluster": cluster_summary.largest_cluster,
        "average_cluster_size": round(avg_cluster_size, 2),
        "unclustered": cluster_summary.unclustered,
        "error_type_distribution": dict(error_type_counts),
        "match_type_distribution": match_type_counts
    }
