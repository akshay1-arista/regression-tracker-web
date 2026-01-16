/**
 * Trends Alpine.js Component
 * Manages test trends data and filtering
 */

function trendsData(release, module) {
    return {
        // State
        release: release,
        module: module,
        trends: [],
        metadata: null,
        loading: true,
        error: null,
        filters: {
            flaky_only: false,
            always_failing_only: false,
            new_failures_only: false
        },
        pagination: {
            skip: 0,
            limit: 100
        },

        /**
         * Initialize trends page
         */
        async init() {
            try {
                this.loading = true;
                this.error = null;
                await this.loadTrends();
            } catch (err) {
                console.error('Initialization error:', err);
                this.error = 'Failed to initialize trends: ' + err.message;
            } finally {
                this.loading = false;
            }
        },

        /**
         * Load trends with current filters
         */
        async loadTrends() {
            try {
                const params = new URLSearchParams();
                params.append('skip', this.pagination.skip);
                params.append('limit', this.pagination.limit);

                if (this.filters.flaky_only) {
                    params.append('flaky_only', 'true');
                }
                if (this.filters.always_failing_only) {
                    params.append('always_failing_only', 'true');
                }
                if (this.filters.new_failures_only) {
                    params.append('new_failures_only', 'true');
                }

                const response = await fetch(
                    `/api/v1/trends/${this.release}/${this.module}?${params.toString()}`
                );

                if (!response.ok) {
                    throw new Error(`Failed to load trends: ${response.statusText}`);
                }

                const data = await response.json();
                this.trends = data.items;
                this.metadata = data.metadata;
            } catch (err) {
                console.error('Load trends error:', err);
                this.error = 'Failed to load trends: ' + err.message;
            }
        },

        /**
         * Toggle filter
         */
        toggleFilter(filterName) {
            if (filterName === 'flaky') {
                this.filters.flaky_only = !this.filters.flaky_only;
            } else if (filterName === 'always_failing') {
                this.filters.always_failing_only = !this.filters.always_failing_only;
            } else if (filterName === 'new_failures') {
                this.filters.new_failures_only = !this.filters.new_failures_only;
            }

            // Reset pagination and reload
            this.pagination.skip = 0;
            this.loadTrends();
        },

        /**
         * Clear all filters
         */
        clearFilters() {
            this.filters.flaky_only = false;
            this.filters.always_failing_only = false;
            this.filters.new_failures_only = false;
            this.pagination.skip = 0;
            this.loadTrends();
        },

        /**
         * Check if any filters are active
         */
        hasActiveFilters() {
            return this.filters.flaky_only ||
                   this.filters.always_failing_only ||
                   this.filters.new_failures_only;
        },

        /**
         * Next page
         */
        nextPage() {
            if (this.metadata && this.metadata.has_next) {
                this.pagination.skip += this.pagination.limit;
                this.loadTrends();
            }
        },

        /**
         * Previous page
         */
        previousPage() {
            if (this.metadata && this.metadata.has_previous) {
                this.pagination.skip = Math.max(0, this.pagination.skip - this.pagination.limit);
                this.loadTrends();
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
         * Get job result CSS class
         */
        getJobResultClass(status) {
            const statusMap = {
                'PASSED': 'job-result passed',
                'FAILED': 'job-result failed',
                'SKIPPED': 'job-result skipped',
                'ERROR': 'job-result error'
            };
            return statusMap[status] || 'job-result';
        },

        /**
         * Get rerun info for tooltip
         */
        getRerunInfo(trend, job_id) {
            const rerunInfo = trend.rerun_info_by_job[job_id];
            if (!rerunInfo || !rerunInfo.was_rerun) {
                return '';
            }
            if (rerunInfo.rerun_still_failed) {
                return ' (Rerun - Still Failed)';
            }
            return ' (Rerun)';
        }
    };
}
