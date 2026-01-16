/**
 * Dashboard Alpine.js Component
 * Manages dashboard data and interactions
 */

function dashboardData() {
    return {
        // State
        releases: [],
        modules: [],
        recentJobs: [],
        passRateHistory: [],
        summary: null,
        selectedRelease: null,
        selectedModule: null,
        loading: true,
        error: null,
        autoRefresh: false,
        refreshInterval: null,
        chart: null,

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
                    await this.loadModules();
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
         * Load modules for selected release
         */
        async loadModules() {
            if (!this.selectedRelease) return;

            try {
                const response = await fetch(`/api/v1/dashboard/modules/${this.selectedRelease}`);
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
                const response = await fetch(
                    `/api/v1/dashboard/summary/${this.selectedRelease}/${this.selectedModule}`
                );
                if (!response.ok) {
                    throw new Error(`Failed to load summary: ${response.statusText}`);
                }

                const data = await response.json();
                this.summary = data.summary;
                this.recentJobs = data.recent_jobs;
                this.passRateHistory = data.pass_rate_history;

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

            // Create new chart
            this.chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: this.passRateHistory.map(item => `Job ${item.job_id}`),
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
