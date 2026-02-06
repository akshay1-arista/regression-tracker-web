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
            interval_hours: 12,
            scheduler: {}
        },
        settings: [],
        releases: [],

        // PIN Authentication
        adminPin: null,
        showPinModal: false,
        pinInput: '',
        pinError: null,

        // Polling controls
        updatingPolling: false,
        newIntervalHours: 12,

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

        // On-Demand Polling
        discovering: false,
        discoveryComplete: false,
        discoveredJobs: [],
        selectedJobs: [],

        // Database Maintenance
        syncingBuilds: false,
        syncResults: null,

        // Bug Tracking
        bugTracking: {
            lastUpdate: null,
            totalBugs: 0,
            vleiBugs: 0,
            vlengBugs: 0,
            updating: false,
            updateMessage: '',
            updateSuccess: false
        },

        // Metadata Sync
        metadataSync: {
            enabled: false,
            intervalHours: 24,
            nextRun: null,
            lastSync: null,
            syncing: false,
            updating: false,
            message: '',
            messageSuccess: false,
            showDetailsModal: false,
            detailsLoading: false,
            detailsHtml: '',
            selectedRelease: ''  // Empty string = All Releases (Global)
        },

        // Computed properties
        get jobsByRelease() {
            const grouped = {};
            for (const job of this.discoveredJobs) {
                if (!grouped[job.release]) {
                    grouped[job.release] = [];
                }
                grouped[job.release].push(job);
            }
            // Sort builds within each release by build_number descending
            for (const release in grouped) {
                grouped[release].sort((a, b) => b.build_number - a.build_number);
            }
            return grouped;
        },

        get allSelected() {
            return this.discoveredJobs.length > 0 &&
                   this.selectedJobs.length === this.discoveredJobs.length;
        },

        /**
         * Initialize admin page
         */
        async init() {
            console.log('Admin page initializing...');

            // Prompt for PIN first
            await this.promptForPin();

            try {
                this.loading = true;
                this.error = null;

                await Promise.all([
                    this.loadPollingStatus(),
                    this.loadSettings(),
                    this.loadReleases(),
                    this.loadBugStatus(),
                    this.loadMetadataSyncStatus()
                ]);

                // Set initial interval value
                this.newIntervalHours = this.pollingStatus.interval_hours || 12;

                console.log('Admin page loaded successfully');
            } catch (err) {
                console.error('Initialization error:', err);
                this.error = 'Failed to load admin settings: ' + err.message;

                // Check if error is auth-related
                if (err.message.includes('401') || err.message.includes('403')) {
                    this.adminPin = null;
                    await this.promptForPin();
                }
            } finally {
                this.loading = false;
            }
        },

        /**
         * Prompt for admin PIN
         */
        async promptForPin() {
            return new Promise((resolve) => {
                this.showPinModal = true;
                this.pinInput = '';
                this.pinError = null;

                // Store resolve function for later
                this._pinPromiseResolve = resolve;
            });
        },

        /**
         * Submit PIN
         */
        async submitPin() {
            if (!this.pinInput) {
                this.pinError = 'Please enter a PIN';
                return;
            }

            // Store PIN in memory (not localStorage for security)
            this.adminPin = this.pinInput;
            this.showPinModal = false;
            this.pinError = null;
            this.pinInput = '';

            // Resolve the promise from promptForPin
            if (this._pinPromiseResolve) {
                this._pinPromiseResolve();
                this._pinPromiseResolve = null;
            }
        },

        /**
         * Cancel PIN entry
         */
        cancelPin() {
            this.showPinModal = false;
            this.pinError = null;
            this.pinInput = '';

            // Redirect away from admin page
            window.location.href = '/';
        },

        /**
         * Get headers with PIN authentication
         */
        getAuthHeaders() {
            const headers = {
                'Content-Type': 'application/json'
            };

            if (this.adminPin) {
                headers['X-Admin-PIN'] = this.adminPin;
            }

            return headers;
        },

        /**
         * Handle authentication errors
         */
        async handleAuthError(response) {
            if (response.status === 401 || response.status === 403) {
                // Invalid or missing PIN
                this.adminPin = null;
                this.pinError = 'Invalid PIN. Please try again.';
                await this.promptForPin();
                return true;
            }
            return false;
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
            const response = await fetch('/api/v1/admin/settings', {
                headers: this.getAuthHeaders()
            });

            if (!response.ok) {
                const wasAuthError = await this.handleAuthError(response);
                if (wasAuthError) {
                    // Retry after re-authentication
                    return this.loadSettings();
                }
                throw new Error('Failed to load settings');
            }

            this.settings = await response.json();
        },

        /**
         * Load releases
         */
        async loadReleases() {
            const response = await fetch('/api/v1/admin/releases', {
                headers: this.getAuthHeaders()
            });

            if (!response.ok) {
                const wasAuthError = await this.handleAuthError(response);
                if (wasAuthError) {
                    // Retry after re-authentication
                    return this.loadReleases();
                }
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
            // Validate: 0.25 hours (15 min) to 168 hours (1 week)
            if (this.newIntervalHours < 0.25 || this.newIntervalHours > 168) {
                alert('Interval must be between 0.25 and 168 hours\n(15 minutes to 1 week)');
                return;
            }

            try {
                this.updatingPolling = true;

                const response = await fetch('/api/v1/admin/settings/POLLING_INTERVAL_HOURS', {
                    method: 'PUT',
                    headers: this.getAuthHeaders(),
                    body: JSON.stringify({
                        value: JSON.stringify(this.newIntervalHours)
                    })
                });

                if (!response.ok) {
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        // Retry after re-authentication
                        return this.updateInterval();
                    }
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
                    headers: this.getAuthHeaders(),
                    body: JSON.stringify(this.newRelease)
                });

                if (!response.ok) {
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        // Retry after re-authentication
                        return this.addRelease();
                    }
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
                    headers: this.getAuthHeaders(),
                    body: JSON.stringify({
                        is_active: !release.is_active
                    })
                });

                if (!response.ok) {
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        // Retry after re-authentication
                        return this.toggleReleaseActive(release);
                    }
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
                    method: 'DELETE',
                    headers: this.getAuthHeaders()
                });

                if (!response.ok) {
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        // Retry after re-authentication
                        return this.deleteRelease(release);
                    }
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
         * Update git branch for release
         */
        async updateGitBranch(release, newBranch) {
            // Trim whitespace
            newBranch = newBranch.trim();

            // Skip if value hasn't changed
            if (newBranch === (release.git_branch || '')) {
                return;
            }

            // Validate branch name (alphanumeric, underscores, hyphens, dots)
            if (newBranch && !/^[a-zA-Z0-9_\-\.]+$/.test(newBranch)) {
                alert('Invalid git branch name. Use only letters, numbers, underscores, hyphens, and dots.');
                // Reload to reset the input field
                await this.loadReleases();
                return;
            }

            try {
                const response = await fetch(`/api/v1/admin/releases/${release.id}/git-branch`, {
                    method: 'PUT',
                    headers: this.getAuthHeaders(),
                    body: JSON.stringify({
                        git_branch: newBranch || null  // Send null for empty string
                    })
                });

                if (!response.ok) {
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        // Retry after re-authentication
                        return this.updateGitBranch(release, newBranch);
                    }
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to update git branch');
                }

                const result = await response.json();
                console.log(`Git branch updated for ${release.name}:`, result.message);

                // Reload releases to get updated data
                await this.loadReleases();
            } catch (err) {
                console.error('Update git branch error:', err);
                alert('Error updating git branch: ' + err.message);
                // Reload to reset the input field
                await this.loadReleases();
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
         * Format polling interval for display
         */
        formatInterval(hours) {
            if (!hours) return 'N/A';

            // Less than 1 hour - show in minutes
            if (hours < 1) {
                const minutes = Math.round(hours * 60);
                return `${minutes} minute${minutes !== 1 ? 's' : ''}`;
            }

            // Less than 48 hours - show in hours
            if (hours < 48) {
                // Show decimal if not a whole number
                const displayHours = hours % 1 === 0 ? hours : hours.toFixed(2);
                return `${displayHours} hour${hours !== 1 ? 's' : ''}`;
            }

            // 48 hours or more - show in days
            const days = hours / 24;
            const displayDays = days % 1 === 0 ? days : days.toFixed(1);
            return `${displayDays} day${days !== 1 ? 's' : ''}`;
        },

        /**
         * Discover new jobs from Jenkins
         */
        async discoverJobs() {
            this.discovering = true;
            this.discoveryComplete = false;
            this.discoveredJobs = [];
            this.selectedJobs = [];
            this.error = null;

            try {
                const response = await fetch('/api/v1/jenkins/discover-jobs', {
                    method: 'POST',
                    headers: this.getAuthHeaders()
                });

                if (response.status === 401 || response.status === 403) {
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        // Retry after re-authentication
                        return this.discoverJobs();
                    }
                    return;
                }

                if (!response.ok) {
                    throw new Error(`Discovery failed: ${response.statusText}`);
                }

                const result = await response.json();
                this.discoveredJobs = result.jobs;
                this.discoveryComplete = true;

                // Auto-select all jobs
                this.selectedJobs = this.discoveredJobs.map(j => j.key);

                console.log(`Discovered ${result.total} new jobs`);
            } catch (err) {
                console.error('Discovery error:', err);
                this.error = err.message;
            } finally {
                this.discovering = false;
            }
        },

        /**
         * Toggle select all jobs
         */
        toggleSelectAll() {
            if (this.allSelected) {
                this.selectedJobs = [];
            } else {
                this.selectedJobs = this.discoveredJobs.map(j => j.key);
            }
        },

        /**
         * Download selected jobs
         */
        async downloadSelected() {
            if (this.selectedJobs.length === 0) {
                alert('Please select at least one build');
                return;
            }

            this.downloadInProgress = true;
            this.downloadLogs = [];
            this.error = null;

            try {
                // Filter selected jobs
                const jobs = this.discoveredJobs.filter(j =>
                    this.selectedJobs.includes(j.key)
                );

                const response = await fetch('/api/v1/jenkins/download-selected', {
                    method: 'POST',
                    headers: {
                        ...this.getAuthHeaders(),
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ jobs })
                });

                if (response.status === 401 || response.status === 403) {
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        // Retry after re-authentication
                        return this.downloadSelected();
                    }
                    this.downloadInProgress = false;
                    return;
                }

                if (!response.ok) {
                    throw new Error(`Download failed to start: ${response.statusText}`);
                }

                const result = await response.json();
                this.downloadJobId = result.job_id;

                console.log(`Started download job: ${result.job_id}`);

                // Stream logs via SSE
                this.streamSelectedDownloadLogs(result.job_id);

            } catch (err) {
                console.error('Download error:', err);
                this.error = err.message;
                this.downloadInProgress = false;
            }
        },

        /**
         * Stream download logs via SSE
         */
        streamSelectedDownloadLogs(jobId) {
            // Close existing connection
            if (this.downloadEventSource) {
                this.downloadEventSource.close();
            }

            this.downloadLogs = [];

            const eventSource = new EventSource(`/api/v1/jenkins/download-selected/${jobId}`);
            this.downloadEventSource = eventSource;

            eventSource.onmessage = (event) => {
                const log = JSON.parse(event.data);
                this.downloadLogs.push(log);

                // Auto-scroll to bottom
                this.$nextTick(() => {
                    const logOutput = document.querySelector('.download-progress .log-output');
                    if (logOutput) {
                        logOutput.scrollTop = logOutput.scrollHeight;
                    }
                });
            };

            eventSource.onerror = (error) => {
                console.error('SSE error:', error);
                eventSource.close();
                this.downloadInProgress = false;
                this.downloadEventSource = null;

                // Refresh discoveries after download
                this.discoverJobs();
            };

            eventSource.addEventListener('complete', () => {
                console.log('Download completed');
                eventSource.close();
                this.downloadInProgress = false;
                this.downloadEventSource = null;

                // Refresh discoveries to show updated state
                setTimeout(() => {
                    this.discoverJobs();
                }, 1000);
            });
        },

        /**
         * Sync last_processed_build for all releases
         */
        async syncLastProcessedBuilds() {
            if (this.syncingBuilds) {
                return;
            }

            try {
                this.syncingBuilds = true;
                this.syncResults = null;

                console.log('Starting last_processed_build sync...');

                const response = await fetch('/api/v1/admin/releases/sync-last-processed-builds', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Admin-PIN': this.adminPin
                    }
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const data = await response.json();
                this.syncResults = data;

                console.log('Sync completed:', data);

                // Reload releases to show updated last_processed_build values
                await this.loadReleases();

            } catch (err) {
                console.error('Sync error:', err);
                this.syncResults = {
                    message: `Error: ${err.message}`,
                    releases_processed: 0,
                    updates_made: 0,
                    results: [],
                    error: true
                };
            } finally {
                this.syncingBuilds = false;
            }
        },

        /**
         * Load bug tracking status
         */
        async loadBugStatus() {
            try {
                const response = await fetch('/api/v1/admin/bugs/status');
                const data = await response.json();
                this.bugTracking.lastUpdate = data.last_update;
                this.bugTracking.totalBugs = data.total_bugs;
                this.bugTracking.vleiBugs = data.vlei_bugs;
                this.bugTracking.vlengBugs = data.vleng_bugs;
            } catch (error) {
                console.error('Failed to load bug status:', error);
            }
        },

        /**
         * Format last update timestamp for bug tracking - converts UTC to client's local timezone
         */
        formatBugLastUpdate(timestamp) {
            if (!timestamp) return 'Never';

            // If the timestamp doesn't end with 'Z' and doesn't have timezone offset,
            // assume it's UTC and add 'Z' to ensure proper parsing
            let normalizedTimestamp = timestamp;
            if (!timestamp.endsWith('Z') && !timestamp.match(/[+-]\d{2}:\d{2}$/)) {
                // Replace space with 'T' if present (Python datetime format)
                normalizedTimestamp = timestamp.replace(' ', 'T') + 'Z';
            }

            const date = new Date(normalizedTimestamp);

            // Check if date is valid
            if (isNaN(date.getTime())) {
                return timestamp; // Return original if parsing failed
            }

            return date.toLocaleString();
        },

        /**
         * Manually trigger bug update
         */
        async updateBugs() {
            this.bugTracking.updating = true;
            this.bugTracking.updateMessage = '';

            try {
                const response = await fetch('/api/v1/admin/bugs/update', {
                    method: 'POST',
                    headers: this.getAuthHeaders()
                });

                const data = await response.json();

                if (response.ok) {
                    this.bugTracking.updateSuccess = true;
                    this.bugTracking.updateMessage = data.message;
                    await this.loadBugStatus();
                } else {
                    // Handle auth errors
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        // Retry after re-authentication
                        return this.updateBugs();
                    }
                    this.bugTracking.updateSuccess = false;
                    this.bugTracking.updateMessage = data.detail || 'Update failed';
                }
            } catch (error) {
                this.bugTracking.updateSuccess = false;
                this.bugTracking.updateMessage = 'Update failed: ' + error.message;
            } finally {
                this.bugTracking.updating = false;
            }
        },

        /**
         * Load metadata sync status
         */
        async loadMetadataSyncStatus() {
            try {
                const response = await fetch('/api/v1/admin/metadata-sync/status', {
                    headers: this.getAuthHeaders()
                });
                const data = await response.json();

                if (response.ok) {
                    this.metadataSync.enabled = data.enabled;
                    this.metadataSync.intervalHours = data.interval_hours;
                    this.metadataSync.nextRun = data.next_run;
                    this.metadataSync.lastSync = data.last_sync;
                }
            } catch (error) {
                console.error('Failed to load metadata sync status:', error);
            }
        },

        /**
         * Manually trigger metadata sync
         */
        async triggerMetadataSync() {
            this.metadataSync.syncing = true;
            this.metadataSync.message = '';

            try {
                // Determine endpoint based on selected release
                let endpoint;
                let releaseInfo = '';

                if (this.metadataSync.selectedRelease) {
                    // Release-specific sync
                    const releaseId = this.metadataSync.selectedRelease;
                    const release = this.releases.find(r => r.id === parseInt(releaseId));
                    releaseInfo = release ? ` for ${release.name}` : '';
                    endpoint = `/api/v1/admin/releases/${releaseId}/sync-metadata`;
                } else {
                    // Global sync (all releases)
                    endpoint = '/api/v1/admin/metadata-sync/trigger';
                }

                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: this.getAuthHeaders()
                });

                const data = await response.json();

                if (response.ok) {
                    this.metadataSync.messageSuccess = true;
                    this.metadataSync.message = (data.message || 'Metadata sync started successfully') + releaseInfo;

                    // Poll for status updates every 3 seconds until completion
                    this.pollMetadataSyncStatus();
                } else {
                    // Handle auth errors
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        return this.triggerMetadataSync();
                    }
                    this.metadataSync.messageSuccess = false;
                    this.metadataSync.message = data.detail || 'Sync failed';
                    this.metadataSync.syncing = false;
                }
            } catch (error) {
                this.metadataSync.messageSuccess = false;
                this.metadataSync.message = 'Sync failed: ' + error.message;
                this.metadataSync.syncing = false;
            }
        },

        /**
         * Poll metadata sync status until completion
         */
        async pollMetadataSyncStatus() {
            const checkStatus = async () => {
                await this.loadMetadataSyncStatus();

                // Check if sync is still in progress by looking at last sync
                if (this.metadataSync.lastSync && this.metadataSync.lastSync.status === 'in_progress') {
                    // Still running, check again in 3 seconds
                    setTimeout(checkStatus, 3000);
                } else {
                    // Sync completed or failed
                    this.metadataSync.syncing = false;

                    if (this.metadataSync.lastSync) {
                        if (this.metadataSync.lastSync.status === 'success') {
                            this.metadataSync.messageSuccess = true;
                            this.metadataSync.message = `Sync completed successfully! Added: ${this.metadataSync.lastSync.tests_added}, Updated: ${this.metadataSync.lastSync.tests_updated}, Removed: ${this.metadataSync.lastSync.tests_removed}`;
                        } else if (this.metadataSync.lastSync.status === 'failed') {
                            this.metadataSync.messageSuccess = false;
                            this.metadataSync.message = 'Sync failed. Check logs for details.';
                        }
                    }
                }
            };

            // Start polling after 2 seconds
            setTimeout(checkStatus, 2000);
        },

        /**
         * Toggle metadata sync schedule
         */
        async toggleMetadataSync() {
            this.metadataSync.updating = true;
            this.metadataSync.message = '';

            try {
                const newEnabled = !this.metadataSync.enabled;

                const response = await fetch('/api/v1/admin/metadata-sync/configure', {
                    method: 'POST',
                    headers: {
                        ...this.getAuthHeaders(),
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        enabled: newEnabled,
                        interval_hours: this.metadataSync.intervalHours
                    })
                });

                const data = await response.json();

                if (response.ok) {
                    this.metadataSync.messageSuccess = true;
                    this.metadataSync.message = `Scheduled sync ${newEnabled ? 'enabled' : 'disabled'} successfully`;
                    await this.loadMetadataSyncStatus();
                } else {
                    const wasAuthError = await this.handleAuthError(response);
                    if (wasAuthError) {
                        return this.toggleMetadataSync();
                    }
                    this.metadataSync.messageSuccess = false;
                    this.metadataSync.message = data.detail || 'Configuration update failed';
                }
            } catch (error) {
                this.metadataSync.messageSuccess = false;
                this.metadataSync.message = 'Configuration update failed: ' + error.message;
            } finally {
                this.metadataSync.updating = false;
            }
        },

        /**
         * Show metadata sync history
         */
        async showMetadataSyncHistory() {
            try {
                const response = await fetch('/api/v1/admin/metadata-sync/history?limit=10', {
                    headers: this.getAuthHeaders()
                });

                const data = await response.json();

                if (response.ok && data.length > 0) {
                    let historyText = 'Last 10 Sync Operations:\n\n';
                    data.forEach((log, idx) => {
                        historyText += `${idx + 1}. ${log.started_at} - ${log.status.toUpperCase()}\n`;
                        historyText += `   Commit: ${(log.git_commit_hash || 'N/A').substring(0, 7)}\n`;
                        historyText += `   Tests: ${log.tests_discovered} discovered, ${log.tests_added} added, ${log.tests_updated} updated, ${log.tests_removed} removed\n`;
                        if (log.error_message) {
                            historyText += `   Error: ${log.error_message}\n`;
                        }
                        historyText += '\n';
                    });
                    alert(historyText);
                } else {
                    alert('No sync history available');
                }
            } catch (error) {
                alert('Failed to load sync history: ' + error.message);
            }
        },

        /**
         * View detailed changes for last sync
         */
        async viewSyncChanges() {
            if (!this.metadataSync.lastSync) {
                this.metadataSync.detailsHtml = '<p class="error-message">No sync data available</p>';
                this.metadataSync.showDetailsModal = true;
                return;
            }

            // Show modal and start loading
            this.metadataSync.showDetailsModal = true;
            this.metadataSync.detailsLoading = true;
            this.metadataSync.detailsHtml = '';

            try {
                // Get the latest sync log ID from the database
                const historyResponse = await fetch('/api/v1/admin/metadata-sync/history?limit=1', {
                    headers: this.getAuthHeaders()
                });
                const historyData = await historyResponse.json();

                if (!historyResponse.ok || historyData.length === 0) {
                    this.metadataSync.detailsHtml = '<p class="error-message">No sync logs available</p>';
                    this.metadataSync.detailsLoading = false;
                    return;
                }

                const syncLogId = historyData[0].id;

                // Fetch changes for each type with higher limits
                const [addedRes, updatedRes, removedRes] = await Promise.all([
                    fetch(`/api/v1/admin/metadata-sync/changes/${syncLogId}?change_type=added&limit=200`, {
                        headers: this.getAuthHeaders()
                    }),
                    fetch(`/api/v1/admin/metadata-sync/changes/${syncLogId}?change_type=updated&limit=200`, {
                        headers: this.getAuthHeaders()
                    }),
                    fetch(`/api/v1/admin/metadata-sync/changes/${syncLogId}?change_type=removed&limit=200`, {
                        headers: this.getAuthHeaders()
                    })
                ]);

                const added = await addedRes.json();
                const updated = await updatedRes.json();
                const removed = await removedRes.json();

                // Build HTML report
                let html = '<div class="sync-details-report">';

                // Header
                html += '<div class="report-header" style="margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 2px solid #e0e0e0;">';
                html += `<p style="margin: 0.25rem 0;"><strong>Sync Log ID:</strong> ${syncLogId}</p>`;
                html += `<p style="margin: 0.25rem 0;"><strong>Git Commit:</strong> <code>${(historyData[0].git_commit_hash || 'N/A').substring(0, 10)}</code></p>`;
                html += `<p style="margin: 0.25rem 0;"><strong>Completed:</strong> ${new Date(historyData[0].completed_at).toLocaleString()}</p>`;
                html += '</div>';

                // Statistics Summary
                html += '<div class="report-summary" style="margin-bottom: 1.5rem; padding: 1rem; background: #f5f5f5; border-radius: 4px;">';
                html += '<h4 style="margin-top: 0;">Summary</h4>';
                html += `<p style="margin: 0.25rem 0;"><span style="color: #28a745;">✅ Added:</span> ${added.total_returned || 0}</p>`;
                html += `<p style="margin: 0.25rem 0;"><span style="color: #007bff;">📝 Updated:</span> ${updated.total_returned || 0}</p>`;
                html += `<p style="margin: 0.25rem 0;"><span style="color: #ffc107;">❌ Removed:</span> ${removed.total_returned || 0}</p>`;
                html += '</div>';

                // Added tests section
                if (added.changes && added.changes.length > 0) {
                    html += '<div class="report-section" style="margin-bottom: 2rem;">';
                    html += `<h4 style="color: #28a745; margin-bottom: 1rem;">✅ Added Tests (${added.total_returned})</h4>`;
                    html += '<table class="details-table" style="width: 100%; border-collapse: collapse; font-size: 0.9rem;">';
                    html += '<thead><tr style="background: #f8f9fa; border-bottom: 2px solid #dee2e6;"><th style="padding: 0.5rem; text-align: left;">Test Name</th><th style="padding: 0.5rem; text-align: left;">Topology</th><th style="padding: 0.5rem; text-align: left;">Module</th><th style="padding: 0.5rem; text-align: left;">State</th></tr></thead>';
                    html += '<tbody>';
                    added.changes.forEach((change, idx) => {
                        const bg = idx % 2 === 0 ? '#ffffff' : '#f8f9fa';
                        html += `<tr style="background: ${bg}; border-bottom: 1px solid #e0e0e0;">`;
                        html += `<td style="padding: 0.5rem; font-family: monospace; font-size: 0.85rem;">${change.testcase_name}</td>`;
                        html += `<td style="padding: 0.5rem;">${change.new_values?.topology || 'N/A'}</td>`;
                        html += `<td style="padding: 0.5rem;">${change.new_values?.module || 'N/A'}</td>`;
                        html += `<td style="padding: 0.5rem;"><span class="badge ${change.new_values?.test_state === 'PROD' ? 'badge-success' : 'badge-warning'}">${change.new_values?.test_state || 'N/A'}</span></td>`;
                        html += '</tr>';
                    });
                    html += '</tbody></table>';
                    html += '</div>';
                }

                // Updated tests section
                if (updated.changes && updated.changes.length > 0) {
                    html += '<div class="report-section" style="margin-bottom: 2rem;">';
                    html += `<h4 style="color: #007bff; margin-bottom: 1rem;">📝 Updated Tests (${updated.total_returned})</h4>`;
                    html += '<table class="details-table" style="width: 100%; border-collapse: collapse; font-size: 0.9rem;">';
                    html += '<thead><tr style="background: #f8f9fa; border-bottom: 2px solid #dee2e6;"><th style="padding: 0.5rem; text-align: left;">Test Name</th><th style="padding: 0.5rem; text-align: left;">Changes</th></tr></thead>';
                    html += '<tbody>';
                    updated.changes.forEach((change, idx) => {
                        const bg = idx % 2 === 0 ? '#ffffff' : '#f8f9fa';
                        html += `<tr style="background: ${bg}; border-bottom: 1px solid #e0e0e0;">`;
                        html += `<td style="padding: 0.5rem; font-family: monospace; font-size: 0.85rem;">${change.testcase_name}</td>`;
                        html += '<td style="padding: 0.5rem;"><ul style="margin: 0; padding-left: 1.2rem; list-style: none;">';

                        // Show what changed
                        if (change.old_values && change.new_values) {
                            if (change.old_values.topology !== change.new_values.topology) {
                                html += `<li>Topology: <code>${change.old_values.topology || 'N/A'}</code> → <code>${change.new_values.topology || 'N/A'}</code></li>`;
                            }
                            if (change.old_values.module !== change.new_values.module) {
                                html += `<li>Module: <code>${change.old_values.module || 'N/A'}</code> → <code>${change.new_values.module || 'N/A'}</code></li>`;
                            }
                            if (change.old_values.test_state !== change.new_values.test_state) {
                                html += `<li>State: <code>${change.old_values.test_state || 'N/A'}</code> → <code>${change.new_values.test_state || 'N/A'}</code></li>`;
                            }
                            if (!html.includes('<li>')) {
                                html += '<li style="color: #6c757d;">Metadata refreshed (no visible changes)</li>';
                            }
                        }

                        html += '</ul></td>';
                        html += '</tr>';
                    });
                    html += '</tbody></table>';
                    html += '</div>';
                }

                // Removed tests section
                if (removed.changes && removed.changes.length > 0) {
                    html += '<div class="report-section" style="margin-bottom: 2rem;">';
                    html += `<h4 style="color: #ffc107; margin-bottom: 1rem;">❌ Removed Tests (${removed.total_returned})</h4>`;
                    html += '<table class="details-table" style="width: 100%; border-collapse: collapse; font-size: 0.9rem;">';
                    html += '<thead><tr style="background: #f8f9fa; border-bottom: 2px solid #dee2e6;"><th style="padding: 0.5rem; text-align: left;">Test Name</th><th style="padding: 0.5rem; text-align: left;">Module</th><th style="padding: 0.5rem; text-align: left;">Topology</th></tr></thead>';
                    html += '<tbody>';
                    removed.changes.forEach((change, idx) => {
                        const bg = idx % 2 === 0 ? '#ffffff' : '#f8f9fa';
                        html += `<tr style="background: ${bg}; border-bottom: 1px solid #e0e0e0;">`;
                        html += `<td style="padding: 0.5rem; font-family: monospace; font-size: 0.85rem;">${change.testcase_name}</td>`;
                        html += `<td style="padding: 0.5rem;">${change.old_values?.module || 'N/A'}</td>`;
                        html += `<td style="padding: 0.5rem;">${change.old_values?.topology || 'N/A'}</td>`;
                        html += '</tr>';
                    });
                    html += '</tbody></table>';
                    html += '</div>';
                }

                if (!added.changes?.length && !updated.changes?.length && !removed.changes?.length) {
                    html += '<p style="text-align: center; color: #6c757d; padding: 2rem;">No changes found in this sync.</p>';
                }

                html += '</div>';

                this.metadataSync.detailsHtml = html;

            } catch (error) {
                this.metadataSync.detailsHtml = `<p class="error-message">Failed to load sync changes: ${error.message}</p>`;
            } finally {
                this.metadataSync.detailsLoading = false;
            }
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

