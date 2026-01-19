/**
 * Dashboard Alpine.js Component
 * Manages dashboard data and interactions
 */

function dashboardData() {
    return {
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
        loading: true,
        error: null,
        autoRefresh: false,
        refreshInterval: null,
        chart: null,
        moduleBreakdown: [],  // Per-module stats for All Modules view

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
                    await this.loadSummary();
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
         * Load summary data for selected release/module
         */
        async loadSummary() {
            if (!this.selectedRelease || !this.selectedModule) return;

            try {
                // Build URL with optional version parameter
                let url = `/api/v1/dashboard/summary/${this.selectedRelease}/${this.selectedModule}`;
                if (this.selectedVersion) {
                    url += `?version=${encodeURIComponent(this.selectedVersion)}`;
                }

                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`Failed to load summary: ${response.statusText}`);
                }

                const data = await response.json();
                this.summary = data.summary;
                this.recentJobs = data.recent_jobs;
                this.passRateHistory = data.pass_rate_history;

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
            }
        },

        /**
         * Load priority statistics for a specific job or parent_job_id
         */
        async loadPriorityStats(jobId) {
            if (!this.selectedRelease || !this.selectedModule || !jobId) return;

            try {
                // Use different endpoint for All Modules view
                let url;
                if (this.selectedModule === '__all__') {
                    // All Modules view - use parent_job_id
                    url = `/api/v1/dashboard/priority-stats/${this.selectedRelease}/__all__/${jobId}?compare=true`;
                } else {
                    // Single module view - use job_id
                    url = `/api/v1/dashboard/priority-stats/${this.selectedRelease}/${this.selectedModule}/${jobId}?compare=true`;
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

            // Create new chart
            this.chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Pass Rate (%)',
                        data: this.passRateHistory.map(item => item.pass_rate),
                        borderColor: 'rgb(37, 99, 235)',
                        backgroundColor: 'rgba(37, 99, 235, 0.1)',
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
         * Format date
         */
        formatDate(dateString) {
            if (!dateString) return 'N/A';
            const date = new Date(dateString);
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
    };
}
