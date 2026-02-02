/**
 * Dashboard Alpine.js Component
 * Manages dashboard data and interactions
 */

// Register Alpine component before Alpine initializes
document.addEventListener('alpine:init', () => {
    Alpine.data('dashboardData', () => ({
        // State
        releases: [],
        modules: [],
        versions: [],
        recentJobs: [],
        passRateHistory: [],
        priorityStats: [],
        priorityStatsError: false,
        summary: null,
        topImpactingBugs: [],  // Top VLEI/VLENG bugs by impacted case count
        selectedRelease: null,
        selectedModule: null,
        selectedVersion: '',
        selectedPriorities: [],  // Selected priorities for module breakdown filtering
        availablePriorities: ['P0', 'P1', 'P2', 'P3', 'UNKNOWN'],  // Available priority options
        selectedTestState: 'ALL',  // Selected test state for filtering (ALL, PROD, or STAGING)
        loading: true,
        error: null,
        chart: null,
        moduleBreakdown: [],  // Per-module stats for All Modules view
        excludeFlaky: false,  // Checkbox state for excluding flaky tests from pass rate history
        excludeFlakyPriorityStats: false,  // Checkbox state for excluding flaky tests from priority stats
        excludeFlakyModuleStats: false,  // Checkbox state for excluding flaky tests from module stats
        passedFlakyStats: [],  // Priority breakdown for flaky tests that PASSED in current job
        newFailureStats: [],  // Priority breakdown for new failures

        // Not Run modal state
        showNotRunModal: false,
        notRunData: null,
        notRunLoading: false,
        notRunContext: null,  // { type: 'priority'|'module', value: string, test_state: string }
        notRunLimit: 100,
        notRunOffset: 0,
        notRunFilters: {
            component: '',
            topology: ''
        },

        // Bug Impact modal state
        showBugImpactModal: false,
        bugImpactData: null,
        bugImpactLoading: false,
        currentBug: null,

        // Test execution history modal (nested)
        showTestHistoryModal: false,
        testHistoryData: null,
        testHistoryLoading: false,
        currentTestName: null,
        testHistoryLimit: 100,
        testHistoryOffset: 0,

        // Request tracking to prevent race conditions
        // Map of request keys to AbortControllers for canceling stale requests
        _pendingRequests: new Map(),

        /**
         * Make an async request with automatic cancellation of previous requests
         * @param {string} key - Unique key for this request type (e.g., 'summary', 'module_breakdown')
         * @param {string} url - URL to fetch
         * @param {object} options - Additional fetch options
         * @returns {Promise<object|null>} Response JSON or null if cancelled
         */
        async makeRequest(key, url, options = {}) {
            // Cancel previous request for this key
            if (this._pendingRequests.has(key)) {
                this._pendingRequests.get(key).abort();
            }

            const controller = new AbortController();
            this._pendingRequests.set(key, controller);

            try {
                const response = await fetch(url, {
                    ...options,
                    signal: controller.signal
                });

                // Request completed successfully - remove from pending
                this._pendingRequests.delete(key);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                return await response.json();
            } catch (err) {
                // Remove from pending requests
                this._pendingRequests.delete(key);

                // If request was aborted, return null (not an error)
                if (err.name === 'AbortError') {
                    console.log(`Request '${key}' cancelled (newer request in flight)`);
                    return null;
                }

                // Re-throw other errors
                throw err;
            }
        },

        /**
         * Cancel all pending requests
         */
        cancelAllRequests() {
            for (const [key, controller] of this._pendingRequests.entries()) {
                controller.abort();
            }
            this._pendingRequests.clear();
        },

        /**
         * Load top impacting bugs (VLEI/VLENG)
         */
        async loadTopImpactingBugs() {
            try {
                const url = '/api/v1/admin/bugs/top-impacting?limit=10';
                const data = await this.makeRequest('top_impacting_bugs', url);
                if (data) {
                    this.topImpactingBugs = data;
                }
            } catch (err) {
                console.error('Failed to load top impacting bugs:', err);
                // Non-critical, so don't block dashboard loading
            }
        },

        /**
         * Truncate text with ellipsis
         */
        truncateText(text, length) {
            if (!text) return '';
            if (text.length <= length) return text;
            return text.substring(0, length) + '...';
        },

        /**
         * Initialize dashboard
         */
        async init() {
            try {
                this.loading = true;
                this.error = null;

                // Register keyboard event listener for modal accessibility
                window.addEventListener('keydown', this.handleNotRunModalKeydown.bind(this));
                window.addEventListener('keydown', this.handleBugImpactModalKeydown.bind(this));

                // Load top impacting bugs (independent of release)
                this.loadTopImpactingBugs();

                await this.loadReleases();
                if (this.releases.length > 0) {
                    this.selectedRelease = this.releases[0].name;
                    await this.loadVersions();
                }
            } catch (err) {
                console.error('Initialization error:', err);
                this.error = 'Failed to initialize dashboard: ' + err.message;
            } finally {
                this.loading = false;
            }
        },

        /**
         * Load all releases
         */
        async loadReleases() {
            const response = await fetch('/api/v1/dashboard/releases');
            if (!response.ok) {
                throw new Error(`Failed to load releases: ${response.statusText}`);
            }
            this.releases = await response.json();
        },

        /**
         * Load versions for selected release
         */
        async loadVersions() {
            if (!this.selectedRelease) return;

            try {
                const response = await fetch(
                    `/api/v1/dashboard/versions/${this.selectedRelease}`
                );
                if (!response.ok) {
                    throw new Error(`Failed to load versions: ${response.statusText}`);
                }
                this.versions = await response.json();

                // Reset version selection to "All Versions"
                this.selectedVersion = '';

                // Reset exclude flaky checkboxes when release changes
                this.excludeFlaky = false;
                this.excludeFlakyPriorityStats = false;
                this.excludeFlakyModuleStats = false;

                // Load modules (with optional version filter)
                await this.loadModules();
            } catch (err) {
                console.error('Load versions error:', err);
                this.error = 'Failed to load versions: ' + err.message;
            }
        },

        /**
         * Load modules for selected release (optionally filtered by version)
         */
        async loadModules() {
            if (!this.selectedRelease) return;

            try {
                // Build URL with optional version parameter
                let url = `/api/v1/dashboard/modules/${this.selectedRelease}`;
                if (this.selectedVersion) {
                    url += `?version=${encodeURIComponent(this.selectedVersion)}`;
                }

                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`Failed to load modules: ${response.statusText}`);
                }
                this.modules = await response.json();

                if (this.modules.length > 0) {
                    this.selectedModule = this.modules[0].name;
                    // Explicitly call onModuleChange since programmatic changes don't trigger @change
                    await this.onModuleChange();
                } else {
                    this.summary = null;
                    this.recentJobs = [];
                    this.passRateHistory = [];
                }
            } catch (err) {
                console.error('Load modules error:', err);
                this.error = 'Failed to load modules: ' + err.message;
            }
        },

        /**
         * Handle module selection change - resets filters and loads summary
         */
        async onModuleChange() {
            // Reset exclude flaky checkboxes when user manually changes module
            this.excludeFlaky = false;
            this.excludeFlakyPriorityStats = false;
            this.excludeFlakyModuleStats = false;

            // Load summary for new module
            await this.loadSummary();
        },

        /**
         * Load summary data for selected release/module
         */
        async loadSummary() {
            if (!this.selectedRelease || !this.selectedModule) return;

            try {
                // Clear previous data to prevent stale data during transitions
                this.recentJobs = [];
                this.passRateHistory = [];
                // DON'T clear moduleBreakdown here - it's managed separately by loadModuleBreakdown()


                // Build URL with optional version and priorities parameters
                let url = `/api/v1/dashboard/summary/${this.selectedRelease}/${this.selectedModule}`;
                const params = new URLSearchParams();

                if (this.selectedVersion) {
                    params.append('version', this.selectedVersion);
                }

                // Add priorities parameter for All Modules view with module breakdown filtering
                if (this.selectedModule === '__all__' && this.selectedPriorities.length > 0) {
                    params.append('priorities', this.selectedPriorities.join(','));
                }

                // Add test_states parameter
                // When "All" is selected, send both PROD and STAGING for not_run calculation
                if (this.selectedTestState === 'ALL') {
                    params.append('test_states', 'PROD,STAGING');
                } else if (this.selectedTestState) {
                    params.append('test_states', this.selectedTestState);
                }

                // Add exclude_flaky parameter
                // For All Modules view: use excludeFlaky (for pass rate history) OR excludeFlakyModuleStats (for module breakdown)
                // For specific module view: use only excludeFlaky (for pass rate history)
                const shouldExcludeFlaky = this.excludeFlaky || (this.selectedModule === '__all__' && this.excludeFlakyModuleStats);
                if (shouldExcludeFlaky) {
                    params.append('exclude_flaky', 'true');
                }

                const queryString = params.toString();
                if (queryString) {
                    url += `?${queryString}`;
                }

                // Use makeRequest to handle cancellation of stale requests
                const data = await this.makeRequest('summary', url);

                // Request was cancelled (stale), return early
                if (data === null) return;

                this.summary = data.summary;
                this.recentJobs = data.recent_jobs || [];
                this.passRateHistory = data.pass_rate_history || [];

                // Transform priority breakdowns into table format
                // Use passed_flaky_by_priority for table (shows only passed flaky tests)
                this.passedFlakyStats = this.transformPriorityBreakdown(
                    this.summary?.passed_flaky_by_priority || {}
                );
                this.newFailureStats = this.transformPriorityBreakdown(
                    this.summary?.new_failures_by_priority || {}
                );

                // Handle module breakdown for All Modules view
                // Only update if no priority filters are active (otherwise loadModuleBreakdown handles it)
                if (this.selectedPriorities.length === 0) {
                    this.moduleBreakdown = data.module_breakdown || [];
                }
                // If priorities are selected, leave moduleBreakdown unchanged (managed by loadModuleBreakdown)

                // Load priority statistics
                if (this.selectedModule === '__all__') {
                    // For All Modules, use parent_job_id from latest run
                    if (this.summary?.latest_run?.parent_job_id) {
                        await this.loadPriorityStats(this.summary.latest_run.parent_job_id);
                    }
                } else {
                    // For single module, use job_id from latest job
                    if (this.summary?.latest_job?.job_id) {
                        await this.loadPriorityStats(this.summary.latest_job.job_id);
                    }
                }

                // Update chart
                this.$nextTick(() => {
                    this.renderChart();
                });
            } catch (err) {
                console.error('Load summary error:', err);
                this.error = 'Failed to load summary: ' + err.message;
                // Reset arrays to prevent undefined errors in template
                this.recentJobs = [];
                this.passRateHistory = [];
                this.summary = null;
            }
        },

        /**
         * Load priority statistics for a specific job or parent_job_id
         */
        async loadPriorityStats(jobId = null) {
            // If no jobId provided, use the current latest job/run ID
            if (!jobId) {
                if (this.selectedModule === '__all__') {
                    jobId = this.summary?.latest_run?.parent_job_id;
                } else {
                    jobId = this.summary?.latest_job?.job_id;
                }
            }

            if (!this.selectedRelease || !this.selectedModule || !jobId) return;

            try {
                // Build URL with compare, exclude_flaky, and test_states parameters
                const params = new URLSearchParams();
                params.append('compare', 'true');

                // Add exclude_flaky parameter if checkbox is checked
                if (this.excludeFlakyPriorityStats) {
                    params.append('exclude_flaky', 'true');
                }

                // Add test_states parameter
                // When "All" is selected, send both PROD and STAGING for not_run calculation
                if (this.selectedTestState === 'ALL') {
                    params.append('test_states', 'PROD,STAGING');
                } else if (this.selectedTestState) {
                    params.append('test_states', this.selectedTestState);
                }

                // Use different endpoint for All Modules view
                let url;
                if (this.selectedModule === '__all__') {
                    // All Modules view - use parent_job_id
                    url = `/api/v1/dashboard/priority-stats/${this.selectedRelease}/__all__/${jobId}?${params.toString()}`;
                } else {
                    // Single module view - use job_id
                    url = `/api/v1/dashboard/priority-stats/${this.selectedRelease}/${this.selectedModule}/${jobId}?${params.toString()}`;
                }

                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`Failed to load priority stats: ${response.statusText}`);
                }
                this.priorityStats = await response.json();
                this.priorityStatsError = false;
            } catch (err) {
                console.error('Load priority stats error:', err);
                this.priorityStats = [];
                this.priorityStatsError = true;
            }
        },

        /**
         * Load module breakdown for All Modules view
         */
        async loadModuleBreakdown() {
            // Only for All Modules view
            if (this.selectedModule !== '__all__') return;

            const parentJobId = this.summary?.latest_run?.parent_job_id;
            if (!this.selectedRelease || !parentJobId) return;

            try {
                // Build URL with priorities and exclude_flaky parameters
                let url = `/api/v1/dashboard/summary/${this.selectedRelease}/__all__`;
                const params = new URLSearchParams();

                if (this.selectedVersion) {
                    params.append('version', this.selectedVersion);
                }

                // Add priorities parameter for module breakdown filtering
                if (this.selectedPriorities.length > 0) {
                    params.append('priorities', this.selectedPriorities.join(','));
                }

                // Add test_states parameter (match loadSummary behavior)
                if (this.selectedTestState === 'ALL') {
                    params.append('test_states', 'PROD,STAGING');
                } else if (this.selectedTestState) {
                    params.append('test_states', this.selectedTestState);
                }

                // Add exclude_flaky parameter for module breakdown
                if (this.excludeFlakyModuleStats) {
                    params.append('exclude_flaky', 'true');
                }

                const queryString = params.toString();
                if (queryString) {
                    url += `?${queryString}`;
                }

                // Use makeRequest to handle cancellation of stale requests
                const data = await this.makeRequest('module_breakdown', url);

                // Request was cancelled (stale), return early
                if (data === null) return;

                // Only update module breakdown, leave other data intact
                this.moduleBreakdown = data.module_breakdown || [];
            } catch (err) {
                console.error('Load module breakdown error:', err);
                this.moduleBreakdown = [];
            }
        },

        /**
         * Render pass rate history chart
         */
        renderChart() {
            const canvas = document.getElementById('passRateChart');
            if (!canvas || !this.passRateHistory.length) return;

            const ctx = canvas.getContext('2d');

            // Destroy existing chart
            if (this.chart) {
                this.chart.destroy();
            }

            // Generate labels based on view type
            const labels = this.selectedModule === '__all__'
                ? this.passRateHistory.map(item => `Run ${item.parent_job_id || item.job_id}`)
                : this.passRateHistory.map(item => `Job ${item.job_id}`);

            // Determine which pass rate to display
            const passRateData = this.passRateHistory.map(item =>
                this.excludeFlaky && item.adjusted_pass_rate !== undefined
                    ? item.adjusted_pass_rate
                    : item.pass_rate
            );

            // Create new chart
            this.chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: this.excludeFlaky ? 'Pass Rate (Excluding Flaky) (%)' : 'Pass Rate (%)',
                        data: passRateData,
                        borderColor: this.excludeFlaky ? 'rgb(16, 185, 129)' : 'rgb(37, 99, 235)',
                        backgroundColor: this.excludeFlaky ? 'rgba(16, 185, 129, 0.1)' : 'rgba(37, 99, 235, 0.1)',
                        tension: 0.3,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    return `Pass Rate: ${context.parsed.y}%`;
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100,
                            ticks: {
                                callback: function(value) {
                                    return value + '%';
                                }
                            }
                        }
                    }
                }
            });
        },

        /**
         * Handle test state dropdown change (global filter)
         */
        onTestStateChange() {
            // Reload entire dashboard with new filter
            this.loadSummary();
        },

        /**
         * Toggle auto-refresh
         */
        toggleAutoRefresh() {
            if (this.autoRefresh) {
                this.startAutoRefresh();
            } else {
                this.stopAutoRefresh();
            }
        },

        /**
         * Start auto-refresh
         */
        startAutoRefresh() {
            this.refreshInterval = setInterval(() => {
                this.loadSummary();
            }, 60000); // 60 seconds
        },

        /**
         * Stop auto-refresh
         */
        stopAutoRefresh() {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
                this.refreshInterval = null;
            }
        },

        /**
         * Transform priority breakdown dict into table rows
         */
        transformPriorityBreakdown(breakdownDict) {
            const priorities = ['P0', 'P1', 'P2', 'P3', 'UNKNOWN'];
            return priorities.map(priority => ({
                priority: priority,
                count: breakdownDict[priority] || 0
            })).filter(item => item.count > 0);  // Only show priorities with counts > 0
        },

        /**
         * Get flaky count for a specific priority
         */
        getFlakyCount(priority) {
            const stat = this.passedFlakyStats.find(s => s.priority === priority);
            return stat ? stat.count : 0;
        },

        /**
         * Get new failure count for a specific priority
         */
        getNewFailureCount(priority) {
            const stat = this.newFailureStats.find(s => s.priority === priority);
            return stat ? stat.count : 0;
        },

        /**
         * Toggle exclude flaky tests and reload data
         */
        async toggleExcludeFlaky() {
            await this.loadSummary();
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
         * Get comparison indicator for a metric
         * @param {number} delta - Change value (positive or negative)
         * @param {string} metric - Metric type: 'total', 'passed', 'failed', 'pass_rate'
         * @returns {string} Formatted indicator (e.g., "▲ +5" or "▼ -3.2%")
         */
        getComparisonIndicator(delta, metric) {
            if (delta === 0) {
                return ''; // No change
            }

            const arrow = delta > 0 ? '▲' : '▼';
            const sign = delta > 0 ? '+' : '';

            // Format delta based on metric type
            if (metric === 'pass_rate') {
                return `${arrow} ${sign}${delta}%`;
            } else {
                return `${arrow} ${sign}${delta}`;
            }
        },

        /**
         * Get CSS class for comparison indicator based on metric and delta
         * @param {number} delta - Change value
         * @param {string} metric - Metric type: 'total', 'passed', 'failed', 'pass_rate'
         * @returns {string} CSS class name
         */
        getComparisonClass(delta, metric) {
            if (delta === 0) {
                return 'comparison-neutral';
            }

            // For 'failed' and 'error' metrics, increasing is bad (red), decreasing is good (green)
            // For 'passed' and 'pass_rate', increasing is good (green), decreasing is bad (red)
            // For 'total' and 'skipped', change is neutral (blue) - informational only

            if (metric === 'failed' || metric === 'error') {
                return delta > 0 ? 'comparison-bad' : 'comparison-good';
            } else if (metric === 'passed' || metric === 'pass_rate') {
                return delta > 0 ? 'comparison-good' : 'comparison-bad';
            } else if (metric === 'total' || metric === 'skipped') {
                return 'comparison-info';
            }

            return '';
        },

        /**
         * Get tooltip text for comparison
         * @param {object} stat - Priority stat object with comparison data
         * @param {string} metric - Metric type
         * @returns {string} Tooltip text
         */
        getComparisonTooltip(stat, metric) {
            if (!stat.comparison) {
                return 'No previous data for comparison';
            }

            const prev = stat.comparison.previous;
            const current = stat[metric];

            if (metric === 'pass_rate') {
                return `Previous: ${prev.pass_rate}% → Current: ${current}%`;
            } else {
                const metricName = metric.charAt(0).toUpperCase() + metric.slice(1);
                return `Previous ${metricName}: ${prev[metric]} → Current: ${current}`;
            }
        },

        /**
         * Calculate total for a specific field across all priority stats
         * @param {string} field - Field name (total, passed, failed, skipped)
         * @returns {number} Sum of the field across all priorities
         */
        getPriorityStatsTotal(field) {
            if (!this.priorityStats || this.priorityStats.length === 0) {
                return 0;
            }
            return this.priorityStats.reduce((sum, stat) => sum + (stat[field] || 0), 0);
        },

        /**
         * Calculate overall pass rate across all priority stats
         * Matches backend calculation: passed / total * 100 (includes skipped in denominator)
         * @returns {number} Overall pass rate as percentage (0-100)
         */
        getPriorityStatsOverallPassRate() {
            const total = this.getPriorityStatsTotal('total');
            const passed = this.getPriorityStatsTotal('passed');

            if (total === 0) {
                return 0;
            }

            return parseFloat(((passed / total) * 100).toFixed(2));
        },

        /**
         * Calculate total delta for a specific field across all priority stats
         * @param {string} field - Field name (total, passed, failed, skipped, pass_rate)
         * @returns {number} Sum of deltas, or null if no comparison data available
         */
        getPriorityStatsTotalDelta(field) {
            if (!this.priorityStats || this.priorityStats.length === 0) {
                return null;
            }

            // Check if any stat has comparison data
            const hasComparison = this.priorityStats.some(stat => stat.comparison);
            if (!hasComparison) {
                return null;
            }

            // For pass_rate, we need to calculate it differently
            if (field === 'pass_rate') {
                // Current overall pass rate
                const currentPassRate = this.getPriorityStatsOverallPassRate();

                // Calculate previous overall pass rate
                const prevTotal = this.priorityStats.reduce((sum, stat) =>
                    sum + (stat.comparison?.previous?.total || 0), 0);
                const prevPassed = this.priorityStats.reduce((sum, stat) =>
                    sum + (stat.comparison?.previous?.passed || 0), 0);

                if (prevTotal === 0) {
                    return null;
                }

                const prevPassRate = parseFloat(((prevPassed / prevTotal) * 100).toFixed(2));
                return parseFloat((currentPassRate - prevPassRate).toFixed(2));
            }

            // For other fields, sum up the deltas
            const deltaKey = `${field}_delta`;
            return this.priorityStats.reduce((sum, stat) => {
                if (stat.comparison && stat.comparison[deltaKey] !== undefined) {
                    return sum + stat.comparison[deltaKey];
                }
                return sum;
            }, 0);
        },

        /**
         * Check if total row has comparison data available
         * @returns {boolean}
         */
        hasTotalComparison() {
            return this.priorityStats && this.priorityStats.some(stat => stat.comparison);
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
         * View "Not Run" tests for a specific priority or module
         * @param {string} type - 'priority' or 'module'
         * @param {string} value - Priority level (e.g., 'P0') or module name
         */
        async viewNotRunTests(type, value) {
            this.showNotRunModal = true;
            this.notRunLoading = true;
            this.notRunData = null;

            // Get the current job ID (parent_job_id for All Modules, job_id for individual module)
            let jobId;
            if (this.selectedModule === '__all__') {
                jobId = this.summary?.latest_run?.parent_job_id;
            } else {
                jobId = this.summary?.latest_job?.job_id;
            }

            this.notRunContext = {
                type: type,
                value: value,
                test_state: this.selectedTestState,
                job_id: jobId  // Store job ID for job-specific filtering
            };
            this.notRunOffset = 0;
            this.notRunFilters.component = '';
            this.notRunFilters.topology = '';

            await this.loadNotRunTests();
        },

        /**
         * Load "Not Run" tests from API
         */
        async loadNotRunTests() {
            if (!this.notRunContext) return;

            try {
                this.notRunLoading = true;

                const params = new URLSearchParams();
                params.append('has_history', 'false');  // Only tests NOT executed
                params.append('limit', this.notRunLimit);
                params.append('offset', this.notRunOffset);

                // Add job_id for job-specific filtering (if available)
                if (this.notRunContext.job_id) {
                    params.append('job_id', this.notRunContext.job_id);
                }

                // Add context-specific filter
                if (this.notRunContext.type === 'priority') {
                    params.append('priority', this.notRunContext.value);

                    // Also filter by current module if we're in a specific module view
                    if (this.selectedModule && this.selectedModule !== '__all__') {
                        params.append('module', this.selectedModule);
                    }
                } else if (this.notRunContext.type === 'module') {
                    params.append('module', this.notRunContext.value);
                }

                // Add test_state filter (convert "ALL" to "PROD,STAGING")
                if (this.notRunContext.test_state === 'ALL') {
                    params.append('test_state', 'PROD,STAGING');
                } else if (this.notRunContext.test_state) {
                    params.append('test_state', this.notRunContext.test_state);
                }

                // Add component filter
                if (this.notRunFilters.component) {
                    params.append('component', this.notRunFilters.component);
                }

                // Add topology filter
                if (this.notRunFilters.topology) {
                    params.append('topology', this.notRunFilters.topology);
                }

                const url = `/api/v1/search/filtered-testcases?${params.toString()}`;
                const data = await this.makeRequest('not_run_tests', url);

                if (data) {
                    this.notRunData = data;
                }

            } catch (err) {
                console.error('Load not-run tests error:', err);
                this.error = 'Failed to load not-run tests: ' + err.message;
            } finally {
                this.notRunLoading = false;
            }
        },

        /**
         * Close "Not Run" modal
         */
        closeNotRunModal() {
            this.showNotRunModal = false;
            this.notRunData = null;
            this.notRunContext = null;
            this.notRunOffset = 0;
            this.notRunFilters.component = '';
            this.notRunFilters.topology = '';
        },

        /**
         * Get modal title based on context
         */
        getNotRunModalTitle() {
            if (!this.notRunContext) return 'Not Run Tests';

            const testStateLabel = this.notRunContext.test_state === 'ALL'
                ? 'All Test States'
                : this.notRunContext.test_state;

            if (this.notRunContext.type === 'priority') {
                return `Not Run Tests: ${this.notRunContext.value} (${testStateLabel})`;
            } else if (this.notRunContext.type === 'module') {
                return `Not Run Tests: ${this.notRunContext.value} (${testStateLabel})`;
            }

            return 'Not Run Tests';
        },

        /**
         * Load next page of Not Run tests
         */
        async loadNextPageNotRun() {
            if (!this.hasNextPageNotRun()) return;
            this.notRunOffset += this.notRunLimit;
            await this.loadNotRunTests();
        },

        /**
         * Load previous page of Not Run tests
         */
        async loadPreviousPageNotRun() {
            if (!this.hasPreviousPageNotRun()) return;
            this.notRunOffset = Math.max(0, this.notRunOffset - this.notRunLimit);
            await this.loadNotRunTests();
        },

        /**
         * Check if there's a next page
         */
        hasNextPageNotRun() {
            // API returns array; if length === limit, there may be more
            return this.notRunData && this.notRunData.length === this.notRunLimit;
        },

        /**
         * Check if there's a previous page
         */
        hasPreviousPageNotRun() {
            return this.notRunOffset > 0;
        },

        /**
         * Get pagination start index
         */
        getNotRunPaginationStart() {
            return this.notRunOffset + 1;
        },

        /**
         * Get pagination end index
         */
        getNotRunPaginationEnd() {
            return this.notRunOffset + (this.notRunData?.length || 0);
        },

        /**
         * Export Not Run tests to CSV
         */
        exportNotRunToCSV() {
            if (!this.notRunData || this.notRunData.length === 0) return;

            // Define CSV headers
            const headers = ['Test Name', 'Test Case ID', 'Priority', 'Component', 'Module', 'Test State', 'Topology'];

            // Convert data to CSV rows
            const rows = this.notRunData.map(test => [
                test.testcase_name || '',
                test.test_case_id || '',
                test.priority || 'Unknown',
                test.component || '',
                test.module || '',
                test.test_state || '',
                test.topology || ''
            ]);

            // Combine headers and rows
            const csvContent = [
                headers.join(','),
                ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
            ].join('\n');

            // Create download
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);
            link.setAttribute('href', url);

            // Generate filename with context
            const filename = `not-run-tests-${this.notRunContext.value}-${new Date().toISOString().split('T')[0]}.csv`;
            link.setAttribute('download', filename);
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        },

        /**
         * Get unique components from loaded not-run data
         */
        get uniqueComponents() {
            if (!this.notRunData || this.notRunData.length === 0) return [];
            const components = this.notRunData
                .map(test => test.component)
                .filter(c => c && c !== 'N/A');
            return [...new Set(components)].sort();
        },

        /**
         * Get unique topologies from loaded not-run data
         */
        get uniqueTopologies() {
            if (!this.notRunData || this.notRunData.length === 0) return [];
            const topologies = this.notRunData
                .map(test => test.topology)
                .filter(t => t && t !== 'N/A');
            return [...new Set(topologies)].sort();
        },

        /**
         * View impacted test cases for a bug
         */
        async viewBugImpact(bug) {
            this.currentBug = bug;
            this.showBugImpactModal = true;
            this.bugImpactLoading = true;
            this.bugImpactData = null;

            await this.loadBugImpact();
        },

        /**
         * Load bug impact data from API
         */
        async loadBugImpact() {
            if (!this.currentBug) return;

            try {
                this.bugImpactLoading = true;
                const url = `/api/v1/admin/bugs/${this.currentBug.defect_id}/testcases`;
                const data = await this.makeRequest('bug_impact', url);

                if (data) {
                    this.bugImpactData = data;
                }
            } catch (err) {
                console.error('Load bug impact error:', err);
                this.error = 'Failed to load bug impact: ' + err.message;
            } finally {
                this.bugImpactLoading = false;
            }
        },

        /**
         * Close bug impact modal
         */
        closeBugImpactModal() {
            this.showBugImpactModal = false;
            this.bugImpactData = null;
            this.currentBug = null;
        },

        /**
         * Handle keyboard events for bug impact modal
         */
        handleBugImpactModalKeydown(event) {
            if (this.showBugImpactModal && event.key === 'Escape') {
                this.closeBugImpactModal();
            }
        },

        /**
         * View execution history for a test case
         */
        async viewTestHistory(testcaseName) {
            this.showTestHistoryModal = true;
            this.testHistoryLoading = true;
            this.testHistoryData = null;
            this.currentTestName = testcaseName;
            this.testHistoryOffset = 0;
            await this.loadTestHistory();
        },

        /**
         * Load test execution history from API
         */
        async loadTestHistory() {
            if (!this.currentTestName) return;

            try {
                this.testHistoryLoading = true;
                const params = new URLSearchParams();
                params.append('limit', this.testHistoryLimit);
                params.append('offset', this.testHistoryOffset);

                const url = `/api/v1/search/testcases/${encodeURIComponent(this.currentTestName)}?${params.toString()}`;
                const data = await this.makeRequest('test_history', url);

                if (data) {
                    this.testHistoryData = data;
                }
            } catch (err) {
                console.error('Load history error:', err);
                this.error = 'Failed to load test history: ' + err.message;
            } finally {
                this.testHistoryLoading = false;
            }
        },

        /**
         * Close test history modal
         */
        closeTestHistoryModal() {
            this.showTestHistoryModal = false;
            this.testHistoryData = null;
            this.currentTestName = null;
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
         * Handle keyboard events for modal accessibility
         */
        handleNotRunModalKeydown(event) {
            if (this.showNotRunModal && event.key === 'Escape') {
                this.closeNotRunModal();
            }
        },

        /**
         * Cleanup on component destroy
         * Prevents memory leaks from chart and pending requests
         */
        destroy() {
            // Cancel all pending requests
            this.cancelAllRequests();

            // Destroy chart instance
            if (this.chart) {
                this.chart.destroy();
                this.chart = null;
            }

            // Remove keyboard event listener
            window.removeEventListener('keydown', this.handleNotRunModalKeydown.bind(this));
            window.removeEventListener('keydown', this.handleBugImpactModalKeydown.bind(this));
        }
    }));
});
