/**
 * Job Details Alpine.js Component
 * Manages job details data and test results
 */

function jobDetailsData(release, module, job_id) {
    console.log('jobDetailsData function called with:', {release, module, job_id});
    const dataObject = {
        // State
        release: release,
        module: module,
        job_id: job_id,
        job: null,
        tests: [],
        groupedTests: {}, // Grouped by topology > setup_ip
        metadata: null,
        topologies: [],
        loading: true,
        error: null,
        expandedTests: [], // Array to track expanded test keys
        expandedGroups: [], // Array to track expanded topology/setup_ip groups
        abortController: null, // For cancelling in-flight requests
        viewMode: 'grouped', // 'grouped' or 'flat'
        filters: {
            status: '',
            topology: '',
            priority: '',
            search: ''
        },
        pagination: {
            skip: 0,
            limit: 100
        },

        /**
         * Initialize job details page
         */
        async init() {
            console.log('Job details page initializing...');
            try {
                this.loading = true;
                this.error = null;
                await Promise.all([
                    this.loadJobDetails(),
                    this.loadTests()
                ]);
                console.log('Job details loaded successfully');
            } catch (err) {
                console.error('Initialization error:', err);
                this.error = 'Failed to initialize job details: ' + err.message;
            } finally {
                this.loading = false;
            }
        },

        /**
         * Load job details
         */
        async loadJobDetails() {
            try {
                const response = await fetch(
                    `/api/v1/jobs/${this.release}/${this.module}/${this.job_id}`
                );

                if (!response.ok) {
                    throw new Error(`Failed to load job details: ${response.statusText}`);
                }

                const data = await response.json();
                this.job = data.job;

                // Extract unique topologies from statistics
                if (data.statistics && data.statistics.topologies) {
                    this.topologies = data.statistics.topologies;
                } else if (data.statistics && data.statistics.by_topology) {
                    this.topologies = Object.keys(data.statistics.by_topology);
                }
            } catch (err) {
                console.error('Load job details error:', err);
                this.error = 'Failed to load job details: ' + err.message;
            }
        },

        /**
         * Load test results with current filters
         */
        async loadTests() {
            // Switch to flat view when filters are active
            if (this.hasActiveFilters()) {
                this.viewMode = 'flat';
                await this.loadFlatTests();
            } else if (this.viewMode === 'grouped') {
                await this.loadGroupedTests();
            } else {
                await this.loadFlatTests();
            }
        },

        /**
         * Load tests in flat list format (with filters/pagination)
         */
        async loadFlatTests() {
            // Cancel previous request if still in flight
            if (this.abortController) {
                this.abortController.abort();
            }

            // Create new AbortController for this request
            this.abortController = new AbortController();

            try {
                const params = new URLSearchParams();
                params.append('skip', this.pagination.skip);
                params.append('limit', this.pagination.limit);

                if (this.filters.status) {
                    params.append('status', this.filters.status);
                }
                if (this.filters.topology) {
                    params.append('topology', this.filters.topology);
                }
                if (this.filters.priority) {
                    params.append('priority', this.filters.priority);
                }
                if (this.filters.search) {
                    params.append('search', this.filters.search);
                }

                const response = await fetch(
                    `/api/v1/jobs/${this.release}/${this.module}/${this.job_id}/tests?${params.toString()}`,
                    { signal: this.abortController.signal }
                );

                if (!response.ok) {
                    throw new Error(`Failed to load tests: ${response.statusText}`);
                }

                const data = await response.json();
                this.tests = data.items;
                this.metadata = data.metadata;
                this.groupedTests = {};
                this.expandedTests = []; // Reset expanded tests on reload
            } catch (err) {
                // Ignore abort errors (they're expected when cancelling requests)
                if (err.name === 'AbortError') {
                    return;
                }
                console.error('Load tests error:', err);
                this.error = 'Failed to load tests: ' + err.message;
            }
        },

        /**
         * Load tests grouped by topology and setup_ip
         */
        async loadGroupedTests() {
            try {
                console.log('Loading grouped tests...');
                const response = await fetch(
                    `/api/v1/jobs/${this.release}/${this.module}/${this.job_id}/grouped`
                );

                if (!response.ok) {
                    throw new Error(`Failed to load grouped tests: ${response.statusText}`);
                }

                const data = await response.json();
                console.log('Grouped tests data:', data);
                console.log('Number of topologies:', Object.keys(data).length);

                this.groupedTests = data;
                this.tests = [];

                // Calculate total for metadata and auto-expand all groups
                let total = 0;
                const expandedGroups = [];

                Object.keys(data).forEach(topology => {
                    Object.keys(data[topology]).forEach(setupIp => {
                        const tests = data[topology][setupIp];
                        total += tests.length;
                        // Auto-expand all groups on initial load
                        expandedGroups.push(`${topology}-${setupIp}`);
                    });
                });

                this.metadata = { total };
                this.expandedTests = [];
                this.expandedGroups = expandedGroups; // Expand all groups by default

                console.log(`Loaded ${total} tests in ${Object.keys(data).length} topologies`);
                console.log('Expanded groups:', expandedGroups);
                console.log('View mode:', this.viewMode);
            } catch (err) {
                console.error('Load grouped tests error:', err);
                this.error = 'Failed to load grouped tests: ' + err.message;
            }
        },

        /**
         * Clear all filters
         */
        clearFilters() {
            this.filters.status = '';
            this.filters.topology = '';
            this.filters.priority = '';
            this.filters.search = '';
            this.pagination.skip = 0;
            this.loadTests();
        },

        /**
         * Check if any filters are active
         */
        hasActiveFilters() {
            return this.filters.status ||
                   this.filters.topology ||
                   this.filters.priority ||
                   this.filters.search;
        },

        /**
         * Toggle failure message visibility
         */
        toggleTestError(testKey) {
            const index = this.expandedTests.indexOf(testKey);
            if (index === -1) {
                // Add to array - reassign for reactivity
                this.expandedTests = [...this.expandedTests, testKey];
            } else {
                // Remove from array - reassign for reactivity
                this.expandedTests = this.expandedTests.filter(k => k !== testKey);
            }
        },

        /**
         * Toggle group expansion (topology/setup_ip)
         */
        toggleGroup(groupKey) {
            const index = this.expandedGroups.indexOf(groupKey);
            if (index === -1) {
                this.expandedGroups = [...this.expandedGroups, groupKey];
            } else {
                this.expandedGroups = this.expandedGroups.filter(k => k !== groupKey);
            }
        },

        /**
         * Check if a group is expanded
         */
        isGroupExpanded(groupKey) {
            return this.expandedGroups.includes(groupKey);
        },

        /**
         * Get sorted topology keys
         */
        getSortedTopologies() {
            return Object.keys(this.groupedTests).sort();
        },

        /**
         * Get sorted setup IPs for a topology
         */
        getSortedSetupIps(topology) {
            if (!this.groupedTests[topology]) return [];
            return Object.keys(this.groupedTests[topology]).sort();
        },

        /**
         * Get tests for a topology/setup_ip group (already sorted by order_index from backend)
         */
        getTestsForGroup(topology, setupIp) {
            if (!this.groupedTests[topology] || !this.groupedTests[topology][setupIp]) {
                return [];
            }
            return this.groupedTests[topology][setupIp];
        },

        /**
         * Get group statistics
         */
        getGroupStats(tests) {
            const stats = {
                total: tests.length,
                passed: 0,
                failed: 0,
                skipped: 0,
                error: 0
            };

            tests.forEach(test => {
                const status = test.status.toLowerCase();
                if (stats[status] !== undefined) {
                    stats[status]++;
                }
            });

            return stats;
        },

        /**
         * Check if we have grouped tests to display
         */
        hasGroupedTests() {
            return Object.keys(this.groupedTests).length > 0;
        },

        /**
         * Next page
         */
        nextPage() {
            if (this.metadata && this.metadata.has_next) {
                this.pagination.skip += this.pagination.limit;
                this.loadTests();
            }
        },

        /**
         * Previous page
         */
        previousPage() {
            if (this.metadata && this.metadata.has_previous) {
                this.pagination.skip = Math.max(0, this.pagination.skip - this.pagination.limit);
                this.loadTests();
            }
        },

        /**
         * Get current page number
         */
        getCurrentPage() {
            return Math.floor(this.pagination.skip / this.pagination.limit) + 1;
        },

        /**
         * Get total pages
         */
        getTotalPages() {
            if (!this.metadata || !this.metadata.total) return 1;
            return Math.ceil(this.metadata.total / this.pagination.limit);
        },

        /**
         * Get status CSS class
         */
        getStatusClass(status) {
            const statusMap = {
                'PASSED': 'status-passed',
                'FAILED': 'status-failed',
                'SKIPPED': 'status-skipped',
                'ERROR': 'status-error'
            };
            return statusMap[status] || '';
        },

        /**
         * Get priority badge CSS class
         */
        getPriorityBadgeClass(priority) {
            if (!priority) {
                return 'badge priority-unknown';
            }
            const priorityMap = {
                'P0': 'badge priority-p0',
                'P1': 'badge priority-p1',
                'P2': 'badge priority-p2',
                'P3': 'badge priority-p3'
            };
            return priorityMap[priority] || 'badge priority-unknown';
        },

        /**
         * Get pass rate CSS class
         */
        getPassRateClass(passRate) {
            if (!passRate) return '';
            if (passRate >= 90) return 'pass-rate-high';
            if (passRate >= 70) return 'pass-rate-medium';
            return 'pass-rate-low';
        },

        /**
         * Calculate percentage
         */
        getPercentage(value, total) {
            if (!total) return 0;
            return ((value / total) * 100).toFixed(1);
        },

        /**
         * Format date
         */
        formatDate(dateString) {
            if (!dateString) return 'N/A';
            const date = new Date(dateString);
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        }
    };

    console.log('jobDetailsData returning data object with keys:', Object.keys(dataObject));
    return dataObject;
}
