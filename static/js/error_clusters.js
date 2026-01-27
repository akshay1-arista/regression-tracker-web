/**
 * Error Clusters Alpine.js Component
 *
 * Handles the error clustering page for visualizing and analyzing
 * test failure patterns in a job.
 */

function errorClustersApp(release, module, jobId) {
    return {
        // Route parameters
        release: release,
        module: module,
        jobId: jobId,

        // Data
        clusters: [],
        summary: {},

        // Filters and sorting
        minClusterSize: 1,
        sortBy: 'count',

        // Pagination
        skip: 0,
        limit: 20,
        totalClusters: 0,

        // UI state
        loading: false,
        error: null,
        expandedCluster: null,
        showStackTrace: {},
        clusterFilters: {},
        expandedTestErrors: {},  // Track individual test error expansions

        /**
         * Initialize the component
         */
        init() {
            this.fetchClusters();
        },

        /**
         * Fetch error clusters from API
         */
        async fetchClusters() {
            this.loading = true;
            this.error = null;

            try {
                const params = new URLSearchParams({
                    min_cluster_size: this.minClusterSize,
                    sort_by: this.sortBy,
                    skip: this.skip,
                    limit: this.limit
                });

                let response;
                try {
                    response = await fetch(
                        `/api/v1/jobs/${this.release}/${this.module}/${this.jobId}/failures/clustered?${params}`
                    );
                } catch (fetchError) {
                    // Handle network errors (connection refused, timeout, DNS failure)
                    if (fetchError.name === 'TypeError') {
                        throw new Error('Network error - please check your connection and try again');
                    }
                    throw fetchError;
                }

                if (!response.ok) {
                    if (response.status === 404) {
                        throw new Error('Job not found');
                    }
                    if (response.status >= 500) {
                        throw new Error('Server error - please try again later');
                    }
                    throw new Error(`Failed to fetch clusters: ${response.statusText}`);
                }

                const data = await response.json();

                this.clusters = data.clusters || [];
                this.summary = data.summary || {
                    total_failures: 0,
                    unique_clusters: 0,
                    largest_cluster: 0,
                    unclustered: 0
                };
                this.totalClusters = this.summary.unique_clusters;

                // Initialize filters for each cluster
                this.clusters.forEach(cluster => {
                    this.clusterFilters[cluster.signature.fingerprint] = {
                        topology: '',
                        priority: ''
                    };
                });

                // Initialize showStackTrace for each cluster
                this.clusters.forEach(cluster => {
                    if (!(cluster.signature.fingerprint in this.showStackTrace)) {
                        this.showStackTrace[cluster.signature.fingerprint] = false;
                    }
                });

            } catch (err) {
                console.error('Error fetching clusters:', err);
                this.error = err.message;
            } finally {
                this.loading = false;
            }
        },

        /**
         * Toggle cluster expansion
         */
        toggleCluster(fingerprint) {
            if (this.expandedCluster === fingerprint) {
                this.expandedCluster = null;
            } else {
                this.expandedCluster = fingerprint;
            }
        },

        /**
         * Toggle stack trace visibility
         */
        toggleStackTrace(fingerprint) {
            this.showStackTrace[fingerprint] = !this.showStackTrace[fingerprint];
        },

        /**
         * Toggle individual test error visibility
         */
        toggleTestError(testKey) {
            if (this.expandedTestErrors[testKey]) {
                delete this.expandedTestErrors[testKey];
            } else {
                this.expandedTestErrors[testKey] = true;
            }
        },

        /**
         * Get filtered tests for a cluster based on active filters
         */
        getFilteredTests(cluster) {
            const filters = this.clusterFilters[cluster.signature.fingerprint];
            if (!filters) return cluster.test_results || [];

            return cluster.test_results.filter(test => {
                // Filter by topology
                if (filters.topology) {
                    const testTopology = test.topology_metadata || test.jenkins_topology || '';
                    if (testTopology !== filters.topology) return false;
                }

                // Filter by priority
                if (filters.priority) {
                    const testPriority = test.priority || 'UNKNOWN';
                    if (testPriority !== filters.priority) return false;
                }

                return true;
            });
        },

        /**
         * Get CSS class for error type badge
         */
        getErrorTypeBadgeClass(errorType) {
            const typeMap = {
                'AssertionError': 'badge-assertion',
                'IndexError': 'badge-index',
                'TypeError': 'badge-type',
                'TimeoutError': 'badge-timeout',
                'ValueError': 'badge-value',
                'KeyError': 'badge-key',
                'AttributeError': 'badge-attribute',
                'RuntimeError': 'badge-runtime'
            };
            return typeMap[errorType] || 'badge-default';
        },

        /**
         * Get CSS class for priority badge
         */
        getPriorityClass(priority) {
            if (!priority) return 'priority-unknown';

            const priorityMap = {
                'P0': 'priority-p0',
                'P1': 'priority-p1',
                'P2': 'priority-p2',
                'P3': 'priority-p3',
                'UNKNOWN': 'priority-unknown'
            };
            return priorityMap[priority] || 'priority-unknown';
        },

        /**
         * Format file path for display (show only filename and line number)
         */
        formatFilePath(filePath, lineNumber) {
            if (!filePath) return 'Unknown location';

            // Extract just the filename from the path
            const parts = filePath.split('/');
            const fileName = parts[parts.length - 1];

            return lineNumber ? `${fileName}:${lineNumber}` : fileName;
        },

        /**
         * Navigate to next page
         */
        nextPage() {
            if (this.skip + this.limit < this.totalClusters) {
                this.skip += this.limit;
                this.fetchClusters();
                window.scrollTo(0, 0); // Scroll to top
            }
        },

        /**
         * Navigate to previous page
         */
        previousPage() {
            if (this.skip > 0) {
                this.skip = Math.max(0, this.skip - this.limit);
                this.fetchClusters();
                window.scrollTo(0, 0); // Scroll to top
            }
        }
    };
}
