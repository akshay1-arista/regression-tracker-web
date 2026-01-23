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
        selectedRelease: null,
        selectedModule: null,
        selectedVersion: '',
        selectedPriorities: [],  // Selected priorities for module breakdown filtering
        availablePriorities: ['P0', 'P1', 'P2', 'P3', 'UNKNOWN'],  // Available priority options
        loading: true,
        error: null,
        autoRefresh: false,
        refreshInterval: null,
        chart: null,
        moduleBreakdown: [],  // Per-module stats for All Modules view
        excludeFlaky: false,  // Checkbox state for excluding flaky tests from pass rate history
        excludeFlakyPriorityStats: false,  // Checkbox state for excluding flaky tests from priority stats
        excludeFlakyModuleStats: false,  // Checkbox state for excluding flaky tests from module stats
        passedFlakyStats: [],  // Priority breakdown for flaky tests that PASSED in current job
        newFailureStats: [],  // Priority breakdown for new failures

        /**
         * Initialize dashboard
         */
        async init() {
            console.log('Dashboard init started');
            try {
                this.loading = true;
                this.error = null;
                await this.loadReleases();
                console.log('Releases loaded:', this.releases.length);
                if (this.releases.length > 0) {
                    this.selectedRelease = this.releases[0].name;
                    console.log('Selected release:', this.selectedRelease);
                    await this.loadVersions();
                }
            } catch (err) {
                console.error('Initialization error:', err);
                this.error = 'Failed to initialize dashboard: ' + err.message;
            } finally {
                this.loading = false;
                console.log('Dashboard init completed');
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
            if (!this.selectedRelease) {
                console.warn('loadModules: No selectedRelease');
                return;
            }

            try {
                // Build URL with optional version parameter
                let url = `/api/v1/dashboard/modules/${this.selectedRelease}`;
                if (this.selectedVersion) {
                    url += `?version=${encodeURIComponent(this.selectedVersion)}`;
                }

                console.log('loadModules: Fetching URL:', url);
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`Failed to load modules: ${response.statusText}`);
                }
                this.modules = await response.json();
                console.log('loadModules: Received modules:', this.modules.length);

                if (this.modules.length > 0) {
                    this.selectedModule = this.modules[0].name;
                    console.log('loadModules: Selected module:', this.selectedModule);
                    // Explicitly call onModuleChange since programmatic changes don't trigger @change
                    await this.onModuleChange();
                } else {
                    console.log('loadModules: No modules found');
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
            console.log('onModuleChange called for module:', this.selectedModule);
            // Reset exclude flaky checkboxes when user manually changes module
            this.excludeFlaky = false;
            this.excludeFlakyPriorityStats = false;
            this.excludeFlakyModuleStats = false;

            // Load summary for new module
            await this.loadSummary();
            console.log('onModuleChange completed');
        },

        /**
         * Load summary data for selected release/module
         */
        async loadSummary() {
            if (!this.selectedRelease || !this.selectedModule) {
                console.warn('loadSummary: Missing selectedRelease or selectedModule', {
                    selectedRelease: this.selectedRelease,
                    selectedModule: this.selectedModule
                });
                return;
            }

            try {
                // Clear previous data to prevent stale data during transitions
                this.recentJobs = [];
                this.passRateHistory = [];
                this.moduleBreakdown = [];


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

                console.log('loadSummary: Fetching URL:', url);

                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`Failed to load summary: ${response.statusText}`);
                }

                const data = await response.json();
                console.log('loadSummary: Received data:', {
                    release: data.release,
                    module: data.module,
                    summary: data.summary,
                    recent_jobs_count: data.recent_jobs?.length || 0,
                    pass_rate_history_count: data.pass_rate_history?.length || 0,
                    module_breakdown_count: data.module_breakdown?.length || 0
                });

                this.summary = data.summary;
                this.recentJobs = data.recent_jobs || [];
                this.passRateHistory = data.pass_rate_history || [];

                console.log('loadSummary: Set recentJobs length:', this.recentJobs.length);

                // Transform priority breakdowns into table format
                // Use passed_flaky_by_priority for table (shows only passed flaky tests)
                this.passedFlakyStats = this.transformPriorityBreakdown(
                    this.summary?.passed_flaky_by_priority || {}
                );
                this.newFailureStats = this.transformPriorityBreakdown(
                    this.summary?.new_failures_by_priority || {}
                );

                // Handle module breakdown for All Modules view
                if (data.module_breakdown) {
                    this.moduleBreakdown = data.module_breakdown;
                } else {
                    this.moduleBreakdown = [];
                }

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
                // Build URL with compare and exclude_flaky parameters
                const params = new URLSearchParams();
                params.append('compare', 'true');

                // Add exclude_flaky parameter if checkbox is checked
                if (this.excludeFlakyPriorityStats) {
                    params.append('exclude_flaky', 'true');
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

                // Add exclude_flaky parameter for module breakdown
                if (this.excludeFlakyModuleStats) {
                    params.append('exclude_flaky', 'true');
                }

                const queryString = params.toString();
                if (queryString) {
                    url += `?${queryString}`;
                }

                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`Failed to load module breakdown: ${response.statusText}`);
                }

                const data = await response.json();

                // Only update module breakdown, leave other data intact
                if (data.module_breakdown) {
                    this.moduleBreakdown = data.module_breakdown;
                }
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
         * Cleanup on component destroy
         * Prevents memory leaks from chart and intervals
         */
        destroy() {
            // Stop auto-refresh
            this.stopAutoRefresh();

            // Destroy chart instance
            if (this.chart) {
                this.chart.destroy();
                this.chart = null;
            }
        }
    }));
});
