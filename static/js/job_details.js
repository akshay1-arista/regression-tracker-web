/**
 * Job Details Alpine.js Component
 * Manages job details data and test results
 */

// Constants for bug status detection
const CLOSED_BUG_STATUSES = ['done', 'closed', 'resolved'];

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
        modules: [],
        loading: true,
        error: null,
        expandedTests: [], // Array to track expanded test keys
        expandedBugs: [], // Array to track expanded bug lists
        expandedGroups: [], // Array to track expanded topology/setup_ip groups
        abortController: null, // For cancelling in-flight requests
        viewMode: 'grouped', // 'grouped' or 'flat'
        filterDebounce: null, // Debounce timer for filters
        filters: {
            statuses: [],  // Array of selected statuses: ['PASSED', 'FAILED', 'SKIPPED', 'ERROR']
            priorities: [],  // Array of selected priorities: ['P0', 'P1', 'P2', 'P3', 'UNKNOWN']
            topology: '',
            testcase_module: '',
            search: ''
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
         * Initialize job details page
         */
        async init() {
            console.log('Job details page initializing...');
            try {
                this.loading = true;
                this.error = null;

                // Check for query parameters (e.g., ?test=testname from trends page)
                const urlParams = new URLSearchParams(window.location.search);
                const testFilter = urlParams.get('test');
                if (testFilter) {
                    this.filters.search = testFilter;
                    console.log('Auto-filtering for test:', testFilter);
                }

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

                // Extract unique modules from statistics
                if (data.statistics && data.statistics.modules) {
                    this.modules = data.statistics.modules;
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
            // Switch to flat view when filters are active, grouped view when no filters
            if (this.hasActiveFilters()) {
                this.viewMode = 'flat';
                await this.loadFlatTests();
            } else {
                this.viewMode = 'grouped';
                await this.loadGroupedTests();
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

            this.loading = true;
            this.error = null;

            try {
                const params = new URLSearchParams();
                params.append('skip', this.pagination.skip);
                params.append('limit', this.pagination.limit);

                if (this.filters.statuses.length > 0) {
                    // Send as comma-separated string
                    params.append('statuses', this.filters.statuses.join(','));
                }
                if (this.filters.priorities.length > 0) {
                    // Send as comma-separated string (uppercase for API consistency)
                    params.append('priorities', this.filters.priorities.join(','));
                }
                if (this.filters.topology) {
                    params.append('topology', this.filters.topology);
                }
                if (this.filters.testcase_module) {
                    params.append('testcase_module', this.filters.testcase_module);
                }
                if (this.filters.search) {
                    params.append('search', this.filters.search);
                }

                const response = await fetch(
                    `/api/v1/jobs/${this.release}/${this.module}/${this.job_id}/tests?${params.toString()}`,
                    { signal: this.abortController.signal }
                );

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`Server returned ${response.status}: ${errorText || response.statusText}`);
                }

                const data = await response.json();
                this.tests = data.items || [];
                this.metadata = data.metadata;
                this.groupedTests = {};
                this.expandedTests = []; // Reset expanded tests on reload
            } catch (err) {
                // Ignore abort errors (they're expected when cancelling requests)
                if (err.name === 'AbortError') {
                    return;
                }
                console.error('Load tests error:', err);
                this.error = 'Failed to load tests. ' + (err.message || 'Please try again.');
                this.tests = [];
                this.metadata = null;
            } finally {
                this.loading = false;
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
         * Toggle status filter with debouncing
         */
        toggleStatus(status) {
            const index = this.filters.statuses.indexOf(status);
            if (index === -1) {
                // Add status
                this.filters.statuses.push(status);
            } else {
                // Remove status
                this.filters.statuses.splice(index, 1);
            }

            // Reset pagination
            this.pagination.skip = 0;

            // Debounce API call to avoid rapid requests when selecting multiple statuses
            clearTimeout(this.filterDebounce);
            this.filterDebounce = setTimeout(() => {
                this.loadTests();
            }, 300);
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
                this.loadTests();
            }, 300);
        },

        /**
         * Clear all filters
         */
        clearFilters() {
            this.filters.statuses = [];
            this.filters.priorities = [];
            this.filters.topology = '';
            this.filters.testcase_module = '';
            this.filters.search = '';
            this.pagination.skip = 0;
            this.loadTests();
        },

        /**
         * Check if any filters are active
         */
        hasActiveFilters() {
            return this.filters.statuses.length > 0 ||
                   this.filters.priorities.length > 0 ||
                   this.filters.topology ||
                   this.filters.testcase_module ||
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
         * Toggle bug list expansion for a test
         */
        toggleBugs(testKey) {
            const index = this.expandedBugs.indexOf(testKey);
            if (index === -1) {
                // Add to array - reassign for reactivity
                this.expandedBugs = [...this.expandedBugs, testKey];
            } else {
                // Remove from array - reassign for reactivity
                this.expandedBugs = this.expandedBugs.filter(k => k !== testKey);
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
         * Format date - converts UTC timestamp to client's local timezone
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
         * Get bug badge CSS class based on status
         */
        getBugBadgeClass(bug) {
            if (!bug || !bug.status) return 'bug-badge-unknown';

            const status = bug.status.toLowerCase();
            if (CLOSED_BUG_STATUSES.some(closedStatus => status.includes(closedStatus))) {
                return 'bug-badge-closed';
            }
            return 'bug-badge-open';
        },

        /**
         * Get bug tooltip text with details
         */
        getBugTooltipText(bug) {
            if (!bug) return '';

            return `Status: ${bug.status || 'Unknown'}
Priority: ${bug.priority || 'N/A'}
Assignee: ${bug.assignee || 'Unassigned'}

${bug.summary || ''}`;
        },

        /**
         * Get tooltip text for additional bugs
         */
        getAdditionalBugsTooltip(bugs) {
            if (!bugs || bugs.length === 0) return '';

            return bugs.map(b =>
                `${b.defect_id} (${b.status || 'Unknown'})`
            ).join('\n');
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

            await this.loadDetailsHistory();
        },

        /**
         * Load details for current test case
         */
        async loadDetailsHistory() {
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
        async loadNextDetailsPage() {
            if (!this.hasNextDetailsPage()) return;
            this.detailsOffset += this.detailsLimit;
            await this.loadDetailsHistory();
        },

        /**
         * Load previous page of execution history
         */
        async loadPreviousDetailsPage() {
            if (!this.hasPreviousDetailsPage()) return;
            this.detailsOffset = Math.max(0, this.detailsOffset - this.detailsLimit);
            await this.loadDetailsHistory();
        },

        /**
         * Check if there's a next page
         */
        hasNextDetailsPage() {
            return this.detailsData?.pagination?.has_more || false;
        },

        /**
         * Check if there's a previous page
         */
        hasPreviousDetailsPage() {
            return this.detailsOffset > 0;
        },

        /**
         * Get pagination start index
         */
        getDetailsPaginationStart() {
            return this.detailsOffset + 1;
        },

        /**
         * Get pagination end index
         */
        getDetailsPaginationEnd() {
            const total = this.detailsData?.pagination?.total || 0;
            const end = this.detailsOffset + this.detailsLimit;
            return Math.min(end, total);
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

    console.log('jobDetailsData returning data object with keys:', Object.keys(dataObject));
    return dataObject;
}
