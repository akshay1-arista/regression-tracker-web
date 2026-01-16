/**
 * Admin Page Alpine.js Component
 * Manages admin settings, Jenkins polling, and releases
 */

function adminData() {
    return {
        // State
        loading: true,
        error: null,
        pollingStatus: {
            enabled: false,
            interval_minutes: 15,
            scheduler: {}
        },
        settings: [],
        releases: [],

        // Polling controls
        updatingPolling: false,
        newIntervalMinutes: 15,

        // Manual download
        downloadForm: {
            release: '',
            job_url: '',
            skip_existing: true
        },
        downloadInProgress: false,
        downloadJobId: null,
        downloadLogs: [],
        downloadEventSource: null,

        // Release management
        showAddReleaseForm: false,
        newRelease: {
            name: '',
            jenkins_job_url: '',
            is_active: true
        },

        /**
         * Initialize admin page
         */
        async init() {
            console.log('Admin page initializing...');
            try {
                this.loading = true;
                this.error = null;

                await Promise.all([
                    this.loadPollingStatus(),
                    this.loadSettings(),
                    this.loadReleases()
                ]);

                // Set initial interval value
                this.newIntervalMinutes = this.pollingStatus.interval_minutes;

                console.log('Admin page loaded successfully');
            } catch (err) {
                console.error('Initialization error:', err);
                this.error = 'Failed to load admin settings: ' + err.message;
            } finally {
                this.loading = false;
            }
        },

        /**
         * Load polling status
         */
        async loadPollingStatus() {
            const response = await fetch('/api/v1/jenkins/polling/status');

            if (!response.ok) {
                throw new Error('Failed to load polling status');
            }

            this.pollingStatus = await response.json();
        },

        /**
         * Load app settings
         */
        async loadSettings() {
            const response = await fetch('/api/v1/admin/settings');

            if (!response.ok) {
                throw new Error('Failed to load settings');
            }

            this.settings = await response.json();
        },

        /**
         * Load releases
         */
        async loadReleases() {
            const response = await fetch('/api/v1/admin/releases');

            if (!response.ok) {
                throw new Error('Failed to load releases');
            }

            this.releases = await response.json();
        },

        /**
         * Toggle polling on/off
         */
        async togglePolling() {
            try {
                this.updatingPolling = true;

                const response = await fetch('/api/v1/jenkins/polling/toggle', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        enabled: !this.pollingStatus.enabled
                    })
                });

                if (!response.ok) {
                    throw new Error('Failed to toggle polling');
                }

                const result = await response.json();
                alert(result.message);

                // Reload status
                await this.loadPollingStatus();
            } catch (err) {
                console.error('Toggle polling error:', err);
                alert('Error: ' + err.message);
            } finally {
                this.updatingPolling = false;
            }
        },

        /**
         * Update polling interval
         */
        async updateInterval() {
            if (this.newIntervalMinutes < 1 || this.newIntervalMinutes > 1440) {
                alert('Interval must be between 1 and 1440 minutes');
                return;
            }

            try {
                this.updatingPolling = true;

                const response = await fetch('/api/v1/admin/settings/POLLING_INTERVAL_MINUTES', {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        value: JSON.stringify(this.newIntervalMinutes)
                    })
                });

                if (!response.ok) {
                    throw new Error('Failed to update interval');
                }

                alert('Polling interval updated successfully');

                // Reload status
                await this.loadPollingStatus();
            } catch (err) {
                console.error('Update interval error:', err);
                alert('Error: ' + err.message);
            } finally {
                this.updatingPolling = false;
            }
        },

        /**
         * Start manual Jenkins download
         */
        async startDownload() {
            if (!this.downloadForm.release || !this.downloadForm.job_url) {
                alert('Please provide both release name and Jenkins job URL');
                return;
            }

            try {
                this.downloadInProgress = true;
                this.downloadLogs = [];

                // Trigger download
                const response = await fetch('/api/v1/jenkins/download', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(this.downloadForm)
                });

                if (!response.ok) {
                    throw new Error('Failed to start download');
                }

                const result = await response.json();
                this.downloadJobId = result.job_id;

                // Start listening to SSE for progress
                this.streamDownloadLogs(result.job_id);
            } catch (err) {
                console.error('Download error:', err);
                alert('Error: ' + err.message);
                this.downloadInProgress = false;
            }
        },

        /**
         * Stream download logs via SSE
         */
        streamDownloadLogs(jobId) {
            this.downloadEventSource = new EventSource(`/api/v1/jenkins/download/${jobId}`);

            this.downloadEventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.message) {
                    // Add log message
                    this.downloadLogs.push({
                        timestamp: Date.now(),
                        message: data.message
                    });

                    // Auto-scroll log output
                    setTimeout(() => {
                        const logOutput = document.querySelector('.log-output');
                        if (logOutput) {
                            logOutput.scrollTop = logOutput.scrollHeight;
                        }
                    }, 100);
                }

                if (data.status) {
                    // Download completed or failed
                    this.downloadInProgress = false;
                    this.downloadEventSource.close();

                    if (data.status === 'completed') {
                        alert('Download completed successfully!');
                    } else if (data.status === 'failed') {
                        alert('Download failed: ' + (data.error || 'Unknown error'));
                    }
                }
            };

            this.downloadEventSource.onerror = (err) => {
                console.error('SSE error:', err);
                this.downloadInProgress = false;
                this.downloadEventSource.close();
                alert('Error streaming logs');
            };
        },

        /**
         * Add new release
         */
        async addRelease() {
            if (!this.newRelease.name) {
                alert('Please provide a release name');
                return;
            }

            try {
                const response = await fetch('/api/v1/admin/releases', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(this.newRelease)
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to create release');
                }

                alert('Release created successfully');

                // Reload releases
                await this.loadReleases();

                // Reset form
                this.showAddReleaseForm = false;
                this.resetNewRelease();
            } catch (err) {
                console.error('Add release error:', err);
                alert('Error: ' + err.message);
            }
        },

        /**
         * Toggle release active status
         */
        async toggleReleaseActive(release) {
            try {
                const response = await fetch(`/api/v1/admin/releases/${release.id}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        is_active: !release.is_active
                    })
                });

                if (!response.ok) {
                    throw new Error('Failed to update release');
                }

                alert(`Release ${release.is_active ? 'deactivated' : 'activated'} successfully`);

                // Reload releases
                await this.loadReleases();
            } catch (err) {
                console.error('Toggle release error:', err);
                alert('Error: ' + err.message);
            }
        },

        /**
         * Delete release
         */
        async deleteRelease(release) {
            if (release.is_active) {
                alert('Cannot delete an active release. Deactivate it first.');
                return;
            }

            if (!confirm(`Are you sure you want to delete release "${release.name}"? This will delete all associated modules, jobs, and test results.`)) {
                return;
            }

            try {
                const response = await fetch(`/api/v1/admin/releases/${release.id}`, {
                    method: 'DELETE'
                });

                if (!response.ok) {
                    throw new Error('Failed to delete release');
                }

                const result = await response.json();
                alert(result.message);

                // Reload releases
                await this.loadReleases();
            } catch (err) {
                console.error('Delete release error:', err);
                alert('Error: ' + err.message);
            }
        },

        /**
         * Reset new release form
         */
        resetNewRelease() {
            this.newRelease = {
                name: '',
                jenkins_job_url: '',
                is_active: true
            };
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
         * Cleanup on destroy
         */
        destroy() {
            if (this.downloadEventSource) {
                this.downloadEventSource.close();
            }
        }
    };
}
