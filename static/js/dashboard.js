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
        parentJobs: [],  // Available parent job IDs with metadata
        recentJobs: [],
        passRateHistory: [],
        priorityStats: [],
        priorityStatsError: false,
        summary: null,
        selectedRelease: null,
        selectedModule: null,
        selectedVersion: '',
        selectedParentJobId: null,  // Currently selected parent job ID
        selectedEnvironment: 'prod',  // 'prod' or 'staging'
        selectedPriorities: [],  // Selected priorities for module breakdown filtering
        selectedBugPriorities: [],  // Selected priorities for bug tracking filtering
        selectedBugStatuses: ['FAILED', 'SKIPPED'],  // Selected test statuses for bug tracking filtering (default: both)
        availablePriorities: ['P0', 'P1', 'P2', 'P3', 'HIGH', 'MEDIUM', 'UNKNOWN'],  // Available priority options
        availableBugStatuses: ['FAILED', 'SKIPPED'],  // Available test status options for bug tracking
        loading: true,
        summaryLoading: false,  // Loading state for summary section (after initial load)
        error: null,
        chart: null,
        moduleBreakdown: [],  // Per-module stats for All Modules view
        excludeFlaky: false,  // Checkbox state for excluding flaky tests from pass rate history
        excludeFlakyPriorityStats: false,  // Checkbox state for excluding flaky tests from priority stats
        excludeFlakyModuleStats: false,  // Checkbox state for excluding flaky tests from module stats
        passedFlakyStats: [],  // Priority breakdown for flaky tests that PASSED in current job
        newFailureStats: [],  // Priority breakdown for new failures
        flakyStatsError: false,  // Whether flaky stats failed to load
        flakyDataLoaded: false,  // Whether flaky data has been explicitly loaded for current selection
        flakyDataLoading: false,  // Loading state for the "Load Flaky Data" button

        // Bug tracking data
        bugBreakdown: [],  // Bug tracking data per module
        bugDataLoaded: false,  // Whether bug data has been explicitly loaded for current selection
        bugDataLoading: false,  // Loading state for the "Load Bug Data" button

        // Bug details modal state
        showBugModal: false,
        bugModalTitle: '',
        bugModalType: '',  // 'VLEI' or 'VLENG'
        bugModalModule: '',
        bugModalData: [],
        bugModalLoading: false,
        bugModalError: null,

        // Affected tests modal state
        showTestsModal: false,
        testsModalTitle: '',
        testsModalDefectId: '',
        testsModalModule: '',
        testsModalData: [],
        testsModalLoading: false,
        testsModalError: null,

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
         * Initialize dashboard
         */
        async init() {
            try {
                this.loading = true;
                this.error = null;
                await this.loadReleases();
                if (this.releases.length > 0) {
                    this.selectedRelease = this.releases[0].name;
                    await this.loadVersionsAndModules();
                }
            } catch (err) {
                console.error('Initialization error:', err);
                this.error = 'Failed to initialize dashboard: ' + err.message;
            } finally {
                this.loading = false;
            }
        },

        /**
         * Get environment query parameter string
         */
        envParam() {
            return `environment=${this.selectedEnvironment}`;
        },

        /**
         * Switch between prod and staging environments
         */
        async switchEnvironment(env) {
            if (this.selectedEnvironment === env) return;
            this.selectedEnvironment = env;
            // Reset downstream state
            this.selectedVersion = '';
            this.selectedModule = null;
            this.selectedParentJobId = null;
            this.parentJobs = [];
            this.summary = null;
            this.recentJobs = [];
            this.passRateHistory = [];
            this.priorityStats = [];
            this.moduleBreakdown = [];
            this.bugBreakdown = [];
            this.bugDataLoaded = false;
            // Reload from versions onward
            if (this.selectedRelease) {
                await this.loadVersionsAndModules();
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
        async loadVersionsAndModules() {
            if (!this.selectedRelease) return;

            // Reset version selection and flaky checkboxes immediately
            this.selectedVersion = '';
            this.excludeFlaky = false;
            this.excludeFlakyPriorityStats = false;
            this.excludeFlakyModuleStats = false;

            try {
                // Fetch versions and modules (for "All Versions") in parallel — they don't depend on each other
                const [versionsResp, modulesResp] = await Promise.all([
                    fetch(`/api/v1/dashboard/versions/${this.selectedRelease}?${this.envParam()}`),
                    fetch(`/api/v1/dashboard/modules/${this.selectedRelease}?${this.envParam()}`)
                ]);

                if (!versionsResp.ok) {
                    throw new Error(`Failed to load versions: ${versionsResp.statusText}`);
                }
                if (!modulesResp.ok) {
                    throw new Error(`Failed to load modules: ${modulesResp.statusText}`);
                }

                [this.versions, this.modules] = await Promise.all([
                    versionsResp.json(),
                    modulesResp.json()
                ]);

                if (this.modules.length > 0) {
                    this.selectedModule = this.modules[0].name;
                    await this.onModuleChange();
                } else {
                    this.selectedModule = null;
                    this.selectedParentJobId = null;
                    this.parentJobs = [];
                    this.summary = null;
                    this.recentJobs = [];
                    this.passRateHistory = [];
                    this.priorityStats = [];
                    this.priorityStatsError = false;
                    this.moduleBreakdown = [];
                    this.bugBreakdown = [];
                    this.bugDataLoaded = false;
                }
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
                let url = `/api/v1/dashboard/modules/${this.selectedRelease}?${this.envParam()}`;
                if (this.selectedVersion) {
                    url += `&version=${encodeURIComponent(this.selectedVersion)}`;
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
                    this.selectedModule = null;
                    this.selectedParentJobId = null;
                    this.parentJobs = [];
                    this.summary = null;
                    this.recentJobs = [];
                    this.passRateHistory = [];
                    this.priorityStats = [];
                    this.priorityStatsError = false;
                    this.moduleBreakdown = [];
                    this.bugBreakdown = [];
                    this.bugDataLoaded = false;
                    this.passedFlakyStats = [];
                    this.newFailureStats = [];
                    this.showBugModal = false;
                    this.showTestsModal = false;
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

            // Load available parent job IDs for this module
            await this.loadParentJobs();
        },

        /**
         * Load available parent job IDs for selected release/module
         */
        async loadParentJobs() {
            if (!this.selectedRelease || !this.selectedModule) return;

            try {
                // Build URL with optional version parameter
                let url = `/api/v1/dashboard/parent-jobs/${this.selectedRelease}/${this.selectedModule}`;
                const params = new URLSearchParams();
                params.append('environment', this.selectedEnvironment);

                if (this.selectedVersion) {
                    params.append('version', this.selectedVersion);
                }

                url += `?${params.toString()}`;

                // Use makeRequest to handle cancellation of stale requests
                const data = await this.makeRequest('parent_jobs', url);

                // Request was cancelled (stale), return early
                if (data === null) return;

                this.parentJobs = data || [];

                // Auto-select latest (first in list)
                if (this.parentJobs.length > 0) {
                    this.selectedParentJobId = this.parentJobs[0].parent_job_id;
                    // Load dashboard data for selected parent job
                    await this.loadSummary();
                } else {
                    // No parent jobs available - clear all dashboard data
                    this.selectedParentJobId = null;
                    this.summary = null;
                    this.recentJobs = [];
                    this.passRateHistory = [];
                    this.priorityStats = [];
                    this.priorityStatsError = false;
                    this.moduleBreakdown = [];
                    this.bugBreakdown = [];
                    this.bugDataLoaded = false;
                    this.passedFlakyStats = [];
                    this.newFailureStats = [];
                    this.showBugModal = false;
                    this.showTestsModal = false;
                }
            } catch (err) {
                console.error('Error loading parent jobs:', err);
                this.error = 'Failed to load parent job IDs: ' + err.message;
            }
        },

        /**
         * Handle parent job ID selection change
         */
        async onParentJobChange() {
            if (!this.selectedParentJobId) return;

            // loadSummary loads priorityStats in parallel internally (bug breakdown is on-demand)
            await this.loadSummary();

            // Reload module breakdown if All Modules view (depends on summary being loaded)
            if (this.selectedModule === '__all__') {
                await this.loadModuleBreakdown();
            }
        },

        /**
         * Load summary data for selected release/module
         */
        async loadSummary() {
            if (!this.selectedRelease || !this.selectedModule) return;

            try {
                this.summaryLoading = true;

                // Clear previous data to prevent stale data during transitions
                this.recentJobs = [];
                this.passRateHistory = [];
                this.priorityStats = [];
                this.priorityStatsError = false;
                this.moduleBreakdown = [];
                this.passedFlakyStats = [];
                this.newFailureStats = [];

                // Build URL with optional version, parent_job_id, and priorities parameters
                let url = `/api/v1/dashboard/summary/${this.selectedRelease}/${this.selectedModule}`;
                const params = new URLSearchParams();
                params.append('environment', this.selectedEnvironment);

                if (this.selectedVersion) {
                    params.append('version', this.selectedVersion);
                }

                // Add parent job ID parameter
                // - For "All Modules": filters all data (summary, history, module breakdown)
                // - For specific module: filters only summary stats and flaky stats (history/jobs unaffected)
                if (this.selectedParentJobId) {
                    params.append('parent_job_id', this.selectedParentJobId);
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

                // Load priority stats in parallel
                const parallelTasks = [];

                if (this.selectedModule === '__all__') {
                    const jobId = this.selectedParentJobId || this.summary?.latest_run?.parent_job_id;
                    if (jobId) {
                        parallelTasks.push(this.loadPriorityStats(jobId));
                    }
                } else {
                    const jobId = this.selectedParentJobId || this.summary?.latest_job?.job_id;
                    if (jobId) {
                        parallelTasks.push(this.loadPriorityStats(jobId));
                    }
                }

                // Bug breakdown and flaky stats are on-demand - reset when selection changes
                this.bugDataLoaded = false;
                this.bugBreakdown = [];
                this.flakyDataLoaded = false;

                await Promise.all(parallelTasks);

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
            } finally {
                this.summaryLoading = false;
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
                params.append('environment', this.selectedEnvironment);

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

                const data = await this.makeRequest('priority_stats', url);

                // Request was cancelled (stale), return early
                if (data === null) return;

                this.priorityStats = data;
                this.priorityStatsError = false;
            } catch (err) {
                console.error('Load priority stats error:', err);
                this.priorityStats = [];
                this.priorityStatsError = true;
            }
        },

        /**
         * Load flaky/new failure stats asynchronously for All Modules view.
         * Separated from main summary for performance (avoids N+1 module loop).
         */
        /**
         * Load flaky data on demand (works for both single-module and all-modules views).
         * Called explicitly when user clicks "Load Flaky Data" or checks "Exclude Flaky".
         * @param {boolean} withExcludeFlaky - Whether to also compute exclude_flaky adjusted stats
         */
        async loadFlakyData(withExcludeFlaky = false) {
            if (!this.selectedRelease) return;

            // Capture current selection to detect staleness after async fetch
            const requestRelease = this.selectedRelease;
            const requestModule = this.selectedModule;

            try {
                this.flakyDataLoading = true;
                this.flakyStatsError = false;

                const params = new URLSearchParams();
                params.append('environment', this.selectedEnvironment);
                if (this.selectedVersion) {
                    params.append('version', this.selectedVersion);
                }
                // Pass module for single-module view; omit for all-modules
                if (this.selectedModule && this.selectedModule !== '__all__') {
                    params.append('module', this.selectedModule);
                }
                const parentJobId = this.selectedParentJobId ||
                    this.summary?.latest_run?.parent_job_id ||
                    this.summary?.latest_job?.job_id;
                if (parentJobId) {
                    params.append('parent_job_id', parentJobId);
                }
                // Request adjusted stats if exclude_flaky is active
                if (withExcludeFlaky || this.excludeFlaky || this.excludeFlakyModuleStats) {
                    params.append('exclude_flaky', 'true');
                }

                const data = await this.makeRequest(
                    'flaky_data',
                    `/api/v1/dashboard/flaky-summary/${requestRelease}?${params.toString()}`
                );

                if (data === null) return;  // Request was cancelled

                // Discard stale response if user changed selection while request was in-flight
                if (this.selectedRelease !== requestRelease || this.selectedModule !== requestModule) {
                    return;
                }

                // Merge flaky stats into existing summary object
                if (this.summary) {
                    this.summary.flaky_by_priority = data.flaky_by_priority || {};
                    this.summary.passed_flaky_by_priority = data.passed_flaky_by_priority || {};
                    this.summary.new_failures_by_priority = data.new_failures_by_priority || {};
                    this.summary.total_flaky = data.total_flaky || 0;
                    this.summary.total_passed_flaky = data.total_passed_flaky || 0;
                    this.summary.total_new_failures = data.total_new_failures || 0;

                    if (data.adjusted_stats) {
                        this.summary.adjusted_stats = data.adjusted_stats;
                    }

                    // Update priority breakdown tables
                    this.passedFlakyStats = this.transformPriorityBreakdown(
                        data.passed_flaky_by_priority || {}
                    );
                    this.newFailureStats = this.transformPriorityBreakdown(
                        data.new_failures_by_priority || {}
                    );

                    // Update pass rate history with adjusted rates if available
                    if (data.adjusted_pass_rate_history && this.passRateHistory) {
                        const adjustedMap = {};
                        for (const entry of data.adjusted_pass_rate_history) {
                            adjustedMap[entry.parent_job_id] = entry;
                        }
                        for (const historyEntry of this.passRateHistory) {
                            const adjusted = adjustedMap[historyEntry.parent_job_id];
                            if (adjusted) {
                                historyEntry.adjusted_pass_rate = adjusted.adjusted_pass_rate;
                                historyEntry.adjusted_passed = adjusted.adjusted_passed;
                                historyEntry.excluded_passed_flaky_count = adjusted.excluded_passed_flaky_count;
                            }
                        }
                        // Re-render chart with updated data
                        this.$nextTick(() => this.renderChart());
                    }
                }

                this.flakyDataLoaded = true;
            } catch (err) {
                console.error('Load flaky data error:', err);
                this.flakyStatsError = true;
            } finally {
                this.flakyDataLoading = false;
            }
        },

        // Keep old name as alias for backward compatibility (used in retry button template)
        async loadFlakyStats() {
            return this.loadFlakyData();
        },

        /**
         * Load module breakdown for All Modules view
         */
        async loadModuleBreakdown() {
            // Only for All Modules view
            if (this.selectedModule !== '__all__') return;

            const parentJobId = this.selectedParentJobId || this.summary?.latest_run?.parent_job_id;
            if (!this.selectedRelease || !parentJobId) return;

            try {
                // Build URL with priorities and exclude_flaky parameters
                let url = `/api/v1/dashboard/summary/${this.selectedRelease}/__all__`;
                const params = new URLSearchParams();
                params.append('environment', this.selectedEnvironment);
                params.append('parent_job_id', parentJobId);

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

                // Use makeRequest to handle cancellation of stale requests
                const data = await this.makeRequest('module_breakdown', url);

                // Request was cancelled (stale), return early
                if (data === null) return;

                // Only update module breakdown, leave other data intact
                this.moduleBreakdown = data.module_breakdown || [];

                // Bug breakdown is on-demand - reset when module breakdown reloads
                this.bugDataLoaded = false;
                this.bugBreakdown = [];
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
            // If flaky data not loaded yet, load it first (checkbox acts as trigger)
            if (!this.flakyDataLoaded) {
                await this.loadFlakyData(true);
            } else {
                // Re-fetch with updated exclude_flaky flag to get adjusted stats
                await this.loadFlakyData(this.excludeFlaky || this.excludeFlakyModuleStats);
            }
            // Always reload priority stats — it reads excludeFlakyPriorityStats internally
            await this.loadPriorityStats();
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
         * Get tooltip text for module breakdown comparison
         * @param {Object} module - Module stat object with comparison data
         * @param {string} metric - Metric name (total, passed, failed, skipped, pass_rate)
         * @returns {string} Tooltip text
         */
        getModuleComparisonTooltip(module, metric) {
            if (!module.comparison) {
                return 'No previous data for comparison';
            }

            const prev = module.comparison.previous;
            const current = module[metric];

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
         * Load bug breakdown data for selected parent job
         */
        async loadBugBreakdown() {
            if (!this.selectedRelease || !this.selectedModule || !this.selectedParentJobId) {
                this.bugBreakdown = [];
                this.bugDataLoaded = false;
                return;
            }

            try {
                this.bugDataLoading = true;

                let url = `/api/v1/dashboard/bug-breakdown/${this.selectedRelease}/${this.selectedModule}?parent_job_id=${this.selectedParentJobId}`;

                // Add priorities parameter if any are selected
                if (this.selectedBugPriorities.length > 0) {
                    url += `&priorities=${this.selectedBugPriorities.join(',')}`;
                }

                // Add statuses parameter if any are selected
                if (this.selectedBugStatuses.length > 0) {
                    url += `&statuses=${this.selectedBugStatuses.join(',')}`;
                }

                const data = await this.makeRequest('bug_breakdown', url);

                if (data !== null) {  // null = request was cancelled
                    this.bugBreakdown = data;
                    this.bugDataLoaded = true;
                }
            } catch (err) {
                console.error('Failed to load bug breakdown:', err);
                // Don't show error to user - bug tracking is supplementary data
                this.bugBreakdown = [];
                // Keep bugDataLoaded = false so user can retry
            } finally {
                this.bugDataLoading = false;
            }
        },

        /**
         * Reload bug breakdown only if data was already loaded (for filter changes)
         */
        async reloadBugBreakdownIfLoaded() {
            if (this.bugDataLoaded) {
                await this.loadBugBreakdown();
            }
        },

        /**
         * Show bug details modal for a module
         * @param {string} moduleName - Module name
         * @param {string} bugType - 'VLEI' or 'VLENG'
         */
        async showBugDetailsModal(moduleName, bugType) {
            this.showBugModal = true;
            this.bugModalTitle = `${bugType} Bugs - ${moduleName}`;
            this.bugModalType = bugType;
            this.bugModalModule = moduleName;
            this.bugModalData = [];
            this.bugModalLoading = true;
            this.bugModalError = null;

            try {
                let url = `/api/v1/dashboard/bug-details/${this.selectedRelease}/${moduleName}?parent_job_id=${this.selectedParentJobId}&bug_type=${bugType}`;

                // Add statuses parameter if any are selected
                if (this.selectedBugStatuses.length > 0) {
                    url += `&statuses=${this.selectedBugStatuses.join(',')}`;
                }

                const response = await fetch(url);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                this.bugModalData = await response.json();
            } catch (err) {
                console.error('Failed to load bug details:', err);
                this.bugModalError = 'Failed to load bug details: ' + err.message;
            } finally {
                this.bugModalLoading = false;
            }
        },

        /**
         * Close bug details modal
         */
        closeBugModal() {
            this.showBugModal = false;
            this.bugModalData = [];
            this.bugModalError = null;
        },

        /**
         * Show affected tests modal for a module (all bugs)
         * @param {string} moduleName - Module name
         */
        async showAffectedTestsModal(moduleName) {
            // Get all bugs for this module first by showing bug details modal with both types
            this.showBugModal = true;
            this.bugModalTitle = `All Bugs - ${moduleName}`;
            this.bugModalType = '';
            this.bugModalModule = moduleName;
            this.bugModalData = [];
            this.bugModalLoading = true;
            this.bugModalError = null;

            try {
                let url = `/api/v1/dashboard/bug-details/${this.selectedRelease}/${moduleName}?parent_job_id=${this.selectedParentJobId}`;

                // Add statuses parameter if any are selected
                if (this.selectedBugStatuses.length > 0) {
                    url += `&statuses=${this.selectedBugStatuses.join(',')}`;
                }

                const response = await fetch(url);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                this.bugModalData = await response.json();
            } catch (err) {
                console.error('Failed to load bug details:', err);
                this.bugModalError = 'Failed to load bug details: ' + err.message;
            } finally {
                this.bugModalLoading = false;
            }
        },

        /**
         * Show affected tests for a specific bug
         * @param {string} defectId - Bug defect ID
         */
        async showAffectedTestsForBug(defectId) {
            // Hide bug details modal (don't close it - we want to preserve state)
            this.showBugModal = false;

            // Open tests modal
            this.showTestsModal = true;
            this.testsModalTitle = `Tests Affected by ${defectId}`;
            this.testsModalDefectId = defectId;
            this.testsModalModule = this.bugModalModule;
            this.testsModalData = [];
            this.testsModalLoading = true;
            this.testsModalError = null;

            try {
                let url = `/api/v1/dashboard/bug-affected-tests/${this.selectedRelease}/${this.testsModalModule}/${defectId}?parent_job_id=${this.selectedParentJobId}`;

                // Add statuses parameter if any are selected
                if (this.selectedBugStatuses.length > 0) {
                    url += `&statuses=${this.selectedBugStatuses.join(',')}`;
                }

                const response = await fetch(url);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                this.testsModalData = await response.json();
            } catch (err) {
                console.error('Failed to load affected tests:', err);
                this.testsModalError = 'Failed to load affected tests: ' + err.message;
            } finally {
                this.testsModalLoading = false;
            }
        },

        /**
         * Go back from affected tests modal to bug details modal
         */
        goBackToBugModal() {
            // Close tests modal
            this.showTestsModal = false;
            this.testsModalData = [];
            this.testsModalError = null;

            // Re-open bug modal (data is preserved)
            this.showBugModal = true;
        },

        /**
         * Close affected tests modal
         */
        closeTestsModal() {
            this.showTestsModal = false;
            this.testsModalData = [];
            this.testsModalError = null;
        },

        /**
         * Get CSS class for bug status badge
         * @param {string} status - Bug status
         * @returns {string} CSS class name
         */
        getBugStatusClass(status) {
            const statusLower = (status || '').toLowerCase();
            const statusMap = {
                'open': 'status-open',
                'in progress': 'status-in-progress',
                'resolved': 'status-resolved',
                'closed': 'status-closed',
                'reopened': 'status-reopened'
            };
            return statusMap[statusLower] || 'status-unknown';
        },

        /**
         * Truncate text with ellipsis
         * @param {string} text - Text to truncate
         * @param {number} maxLength - Maximum length
         * @returns {string} Truncated text
         */
        truncate(text, maxLength) {
            if (!text || text.length <= maxLength) return text || '';
            return text.substring(0, maxLength) + '...';
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
        }
    }));
});
