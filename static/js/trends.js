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
        filterDebounce: null,  // Debounce timer for priority filters
        jobDisplayLimit: 5,  // Number of recent jobs to display (default: 5)
        availableTestStates: ['PROD', 'STAGING'],  // Available test state options
        filters: {
            failed_only: false,
            flaky_only: false,
            regression_only: false,
            always_failing_only: false,
            new_failures_only: false,
            priorities: [],  // Array of selected priorities: ['P0', 'P1', 'P2', 'P3', 'UNKNOWN']
            test_states: []  // Array of selected test states: ['PROD', 'STAGING']
        },
        pagination: {
            skip: 0,
            limit: 100
        },

        // Execution history modal state
        showDetails: false,
        detailsData: null,
        detailsLoading: false,
        currentTestcaseName: null,
        detailsLimit: 100,
        detailsOffset: 0,

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
            this.loading = true;
            this.error = null;

            try {
                const params = new URLSearchParams();
                params.append('skip', this.pagination.skip);
                params.append('limit', this.pagination.limit);

                if (this.filters.failed_only) {
                    params.append('failed_only', 'true');
                }
                if (this.filters.flaky_only) {
                    params.append('flaky_only', 'true');
                }
                if (this.filters.regression_only) {
                    params.append('regression_only', 'true');
                }
                if (this.filters.always_failing_only) {
                    params.append('always_failing_only', 'true');
                }
                if (this.filters.new_failures_only) {
                    params.append('new_failures_only', 'true');
                }
                if (this.filters.priorities.length > 0) {
                    // Send as comma-separated string (uppercase: P0, P1, P2, P3, UNKNOWN)
                    params.append('priorities', this.filters.priorities.join(','));
                }
                if (this.filters.test_states.length > 0) {
                    // Send as comma-separated string (uppercase: PROD, STAGING)
                    params.append('test_states', this.filters.test_states.join(','));
                }

                const response = await fetch(
                    `/api/v1/trends/${this.release}/${this.module}?${params.toString()}`
                );

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`Server returned ${response.status}: ${errorText || response.statusText}`);
                }

                const data = await response.json();
                this.trends = data.items || [];
                this.metadata = data.metadata;

                // Debug: Log first trend to verify job_modules is present
                if (this.trends.length > 0) {
                    console.log('First trend data:', {
                        test_name: this.trends[0].test_name,
                        job_modules: this.trends[0].job_modules,
                        results_by_job: this.trends[0].results_by_job
                    });
                }
            } catch (err) {
                console.error('Load trends error:', err);
                this.error = 'Failed to load trends. ' + (err.message || 'Please try again.');
                this.trends = [];
                this.metadata = null;
            } finally {
                this.loading = false;
            }
        },

        /**
         * Toggle filter
         */
        toggleFilter(filterName) {
            if (filterName === 'failed') {
                this.filters.failed_only = !this.filters.failed_only;
            } else if (filterName === 'flaky') {
                this.filters.flaky_only = !this.filters.flaky_only;
            } else if (filterName === 'regression') {
                this.filters.regression_only = !this.filters.regression_only;
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
         * Toggle priority filter with debouncing
         */
        togglePriority(priority) {
            const index = this.filters.priorities.indexOf(priority);
            if (index === -1) {
                // Add priority
                this.filters.priorities.push(priority);
            } else {
                // Remove priority
                this.filters.priorities.splice(index, 1);
            }

            // Reset pagination
            this.pagination.skip = 0;

            // Debounce API call to avoid rapid requests when selecting multiple priorities
            clearTimeout(this.filterDebounce);
            this.filterDebounce = setTimeout(() => {
                this.loadTrends();
            }, 300);
        },

        /**
         * Toggle test state filter with debouncing
         */
        toggleTestState(state) {
            const index = this.filters.test_states.indexOf(state);
            if (index === -1) {
                // Add test state
                this.filters.test_states.push(state);
            } else {
                // Remove test state
                this.filters.test_states.splice(index, 1);
            }

            // Reset pagination
            this.pagination.skip = 0;

            // Debounce API call to avoid rapid requests when selecting multiple states
            clearTimeout(this.filterDebounce);
            this.filterDebounce = setTimeout(() => {
                this.loadTrends();
            }, 300);
        },

        /**
         * Clear all filters
         */
        clearFilters() {
            this.filters.failed_only = false;
            this.filters.flaky_only = false;
            this.filters.regression_only = false;
            this.filters.always_failing_only = false;
            this.filters.new_failures_only = false;
            this.filters.priorities = [];
            this.filters.test_states = [];
            this.pagination.skip = 0;
            this.loadTrends();
        },

        /**
         * Check if any filters are active
         */
        hasActiveFilters() {
            return this.filters.failed_only ||
                   this.filters.flaky_only ||
                   this.filters.regression_only ||
                   this.filters.always_failing_only ||
                   this.filters.new_failures_only ||
                   this.filters.priorities.length > 0 ||
                   this.filters.test_states.length > 0;
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
        },

        /**
         * Get priority badge CSS class
         */
        getPriorityBadgeClass(priority) {
            // Normalize priority value to uppercase for consistency
            const normalizedPriority = priority ? priority.toUpperCase() : null;

            if (!normalizedPriority || normalizedPriority === 'UNKNOWN') {
                return 'badge priority-unknown';
            }
            const priorityMap = {
                'P0': 'badge priority-p0',
                'P1': 'badge priority-p1',
                'P2': 'badge priority-p2',
                'P3': 'badge priority-p3'
            };
            return priorityMap[normalizedPriority] || 'badge priority-unknown';
        },

        /**
         * Get priority display text
         */
        getPriorityDisplayText(priority) {
            if (!priority) return 'Unknown';
            const normalizedPriority = priority.toUpperCase();
            return normalizedPriority === 'UNKNOWN' ? 'Unknown' : normalizedPriority;
        },

        /**
         * Get Jenkins module for a specific job in a trend
         * Fallback to path-based module if not available
         */
        getJobModule(trend, job_id) {
            if (trend && trend.job_modules && trend.job_modules[job_id]) {
                return trend.job_modules[job_id];
            }
            // Fallback to the current module (path-based)
            return this.module;
        },

        /**
         * Get filtered job results based on jobDisplayLimit
         * Returns only the N most recent parent jobs or all jobs if limit is 'all'
         *
         * Filters by parent_job_id instead of individual job_ids to ensure
         * ALL sub-jobs from the last N parent jobs are displayed.
         */
        getFilteredJobResults(trend) {
            if (!trend || !trend.results_by_job) {
                return {};
            }

            // If limit is 'all', return all job results
            if (this.jobDisplayLimit === 'all') {
                return trend.results_by_job;
            }

            // Parse limit as number (handles both number and string values)
            const limit = parseInt(this.jobDisplayLimit);
            if (isNaN(limit) || limit <= 0) {
                return trend.results_by_job;  // Fallback to all if invalid
            }

            // If parent_job_ids not provided (backward compatibility), fall back to old behavior
            if (!trend.parent_job_ids) {
                console.warn(
                    `[Backward Compatibility] parent_job_ids not found for test ${trend.test_name}. ` +
                    `Falling back to individual job ID filtering. This may result in inconsistent job display ` +
                    `when tests run in different parent jobs. Consider updating the API to include parent_job_ids.`
                );
                const allJobIds = Object.keys(trend.results_by_job);
                const sortedJobIds = allJobIds.sort((a, b) => parseInt(b) - parseInt(a));
                const limitedJobIds = sortedJobIds.slice(0, limit);

                const filteredResults = {};
                limitedJobIds.forEach(jobId => {
                    filteredResults[jobId] = trend.results_by_job[jobId];
                });
                return filteredResults;
            }

            // Get unique parent_job_ids
            const parentJobIds = new Set(Object.values(trend.parent_job_ids));

            // Sort parent_job_ids (descending - most recent first)
            const sortedParentIds = Array.from(parentJobIds).sort((a, b) => parseInt(b) - parseInt(a));

            // Take only the first N parent jobs
            const limitedParentIds = new Set(sortedParentIds.slice(0, limit));

            // Filter to only jobs belonging to the limited parent jobs
            const filteredResults = {};
            Object.keys(trend.results_by_job).forEach(jobId => {
                const parentJobId = trend.parent_job_ids[jobId];
                if (limitedParentIds.has(parentJobId)) {
                    filteredResults[jobId] = trend.results_by_job[jobId];
                }
            });

            return filteredResults;
        },

        /**
         * View execution history details for a test case
         */
        async viewDetails(testcaseName) {
            this.showDetails = true;
            this.detailsLoading = true;
            this.detailsData = null;
            this.currentTestcaseName = testcaseName;
            this.detailsOffset = 0;

            await this.loadDetails();
        },

        /**
         * Load details for current test case
         */
        async loadDetails() {
            if (!this.currentTestcaseName) return;

            try {
                this.detailsLoading = true;

                const params = new URLSearchParams();
                params.append('limit', this.detailsLimit);
                params.append('offset', this.detailsOffset);

                const response = await fetch(
                    `/api/v1/search/testcases/${encodeURIComponent(this.currentTestcaseName)}?${params.toString()}`
                );

                if (!response.ok) {
                    throw new Error(`Failed to load details: ${response.statusText}`);
                }

                this.detailsData = await response.json();

            } catch (err) {
                console.error('Load details error:', err);
                this.error = 'Failed to load execution history: ' + err.message;
            } finally {
                this.detailsLoading = false;
            }
        },

        /**
         * Close details modal
         */
        closeDetails() {
            this.showDetails = false;
            this.detailsData = null;
            this.currentTestcaseName = null;
            this.detailsOffset = 0;
        },

        /**
         * Load next page of execution history
         */
        async loadNextPage() {
            if (!this.hasNextPage()) return;
            this.detailsOffset += this.detailsLimit;
            await this.loadDetails();
        },

        /**
         * Load previous page of execution history
         */
        async loadPreviousPage() {
            if (!this.hasPreviousPage()) return;
            this.detailsOffset = Math.max(0, this.detailsOffset - this.detailsLimit);
            await this.loadDetails();
        },

        /**
         * Check if there's a next page
         */
        hasNextPage() {
            return this.detailsData?.pagination?.has_more || false;
        },

        /**
         * Check if there's a previous page
         */
        hasPreviousPage() {
            return this.detailsOffset > 0;
        },

        /**
         * Get pagination start index
         */
        getPaginationStart() {
            return this.detailsOffset + 1;
        },

        /**
         * Get pagination end index
         */
        getPaginationEnd() {
            const total = this.detailsData?.pagination?.total || 0;
            const end = this.detailsOffset + this.detailsLimit;
            return Math.min(end, total);
        },

        /**
         * Format date for display - converts UTC timestamp to client's local timezone
         */
        formatDate(dateString) {
            if (!dateString) return 'N/A';

            // If the date string doesn't end with 'Z' and doesn't have timezone offset,
            // assume it's UTC and add 'Z' to ensure proper parsing
            let normalizedDateString = dateString;
            if (!dateString.endsWith('Z') && !dateString.match(/[+-]\d{2}:\d{2}$/)) {
                // Replace space with 'T' if present (Python datetime format)
                normalizedDateString = dateString.replace(' ', 'T') + 'Z';
            }

            const date = new Date(normalizedDateString);

            // Check if date is valid
            if (isNaN(date.getTime())) {
                return dateString; // Return original if parsing failed
            }

            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        },

        /**
         * Get automation status CSS class
         */
        getAutomationStatusClass(status) {
            if (!status) {
                return 'badge automation-unknown';
            }
            const statusMap = {
                'Hapy Automated': 'badge automation-automated',
                'Automated': 'badge automation-automated',
                'Manual': 'badge automation-manual',
                'Not Automated': 'badge automation-manual'
            };
            return statusMap[status] || 'badge automation-unknown';
        }
    };
}
