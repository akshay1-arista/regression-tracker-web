/**
 * Job Details Alpine.js Component
 * Manages job details data and test results
 */

function jobDetailsData(release, module, job_id) {
    return {
        // State
        release: release,
        module: module,
        job_id: job_id,
        job: null,
        tests: [],
        metadata: null,
        topologies: [],
        loading: true,
        error: null,
        expandedTests: [], // Array to track expanded test keys
        filters: {
            status: '',
            topology: '',
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
                if (data.statistics && data.statistics.by_topology) {
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
                if (this.filters.search) {
                    params.append('search', this.filters.search);
                }

                const response = await fetch(
                    `/api/v1/jobs/${this.release}/${this.module}/${this.job_id}/tests?${params.toString()}`
                );

                if (!response.ok) {
                    throw new Error(`Failed to load tests: ${response.statusText}`);
                }

                const data = await response.json();
                this.tests = data.items;
                this.metadata = data.metadata;
                this.expandedTests = []; // Reset expanded tests on reload
            } catch (err) {
                console.error('Load tests error:', err);
                this.error = 'Failed to load tests: ' + err.message;
            }
        },

        /**
         * Clear all filters
         */
        clearFilters() {
            this.filters.status = '';
            this.filters.topology = '';
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
}
