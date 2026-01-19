/**
 * Search Alpine.js Component
 * Manages global test case search and execution history
 */

function searchData() {
    // Constants
    const SEARCH_RESULT_LIMIT = 50;
    const DETAIL_HISTORY_LIMIT = 100;

    return {
        // State
        searchQuery: '',
        results: [],
        loading: false,
        error: null,
        searchPerformed: false,

        // Statistics state (initialize with empty structure to prevent Alpine.js errors)
        statistics: null,
        statisticsLoaded: false,

        // Autocomplete state
        suggestions: [],
        showSuggestions: false,
        autocompleteDebounce: null,
        selectedSuggestionIndex: -1,

        // Details modal state
        showDetails: false,
        detailsData: null,
        detailsLoading: false,
        currentTestcaseName: null,

        // Pagination for details
        detailsLimit: DETAIL_HISTORY_LIMIT,
        detailsOffset: 0,

        /**
         * Initialize search page
         */
        async init() {
            // Fetch statistics on page load
            await this.fetchStatistics();

            // Check if there's a query parameter in URL
            const urlParams = new URLSearchParams(window.location.search);
            const query = urlParams.get('q');

            if (query) {
                this.searchQuery = query;
                await this.performSearch();
            }
        },

        /**
         * Fetch testcase statistics
         */
        async fetchStatistics() {
            try {
                const response = await fetch('/api/v1/search/statistics');

                if (!response.ok) {
                    console.error('Failed to fetch statistics:', response.statusText);
                    return;
                }

                this.statistics = await response.json();
                this.statisticsLoaded = true;
            } catch (err) {
                console.error('Statistics fetch error:', err);
            }
        },

        /**
         * Perform search
         */
        async performSearch() {
            const query = this.searchQuery.trim();
            if (!query) {
                return;
            }

            try {
                this.loading = true;
                this.error = null;
                this.searchPerformed = true;

                const params = new URLSearchParams();
                params.append('q', query);
                params.append('limit', SEARCH_RESULT_LIMIT);

                const response = await fetch(`/api/v1/search/testcases?${params.toString()}`);

                if (!response.ok) {
                    throw new Error(`Search failed: ${response.statusText}`);
                }

                this.results = await response.json();

                // Update URL without reloading page
                const newUrl = new URL(window.location);
                newUrl.searchParams.set('q', query);
                window.history.pushState({}, '', newUrl);

            } catch (err) {
                console.error('Search error:', err);
                this.error = 'Failed to search: ' + err.message;
                this.results = [];
            } finally {
                this.loading = false;
            }
        },

        /**
         * Handle input change for autocomplete
         */
        onSearchInput() {
            const query = this.searchQuery.trim();

            // Hide suggestions if query is too short
            if (query.length < 2) {
                this.showSuggestions = false;
                this.suggestions = [];
                this.selectedSuggestionIndex = -1;
                return;
            }

            // Debounce autocomplete requests
            clearTimeout(this.autocompleteDebounce);
            this.autocompleteDebounce = setTimeout(() => {
                this.fetchSuggestions(query);
            }, 200);
        },

        /**
         * Fetch autocomplete suggestions
         */
        async fetchSuggestions(query) {
            try {
                const params = new URLSearchParams();
                params.append('q', query);
                params.append('limit', '10');

                const response = await fetch(`/api/v1/search/autocomplete?${params.toString()}`);

                if (!response.ok) {
                    console.error('Autocomplete failed:', response.statusText);
                    return;
                }

                this.suggestions = await response.json();
                this.showSuggestions = this.suggestions.length > 0;
                this.selectedSuggestionIndex = -1;
            } catch (err) {
                console.error('Autocomplete error:', err);
            }
        },

        /**
         * Select a suggestion
         */
        selectSuggestion(suggestion) {
            this.searchQuery = suggestion.testcase_name;
            this.showSuggestions = false;
            this.suggestions = [];
            this.selectedSuggestionIndex = -1;
            this.performSearch();
        },

        /**
         * Handle keyboard navigation in suggestions
         */
        handleKeydown(event) {
            if (!this.showSuggestions || this.suggestions.length === 0) {
                return;
            }

            switch (event.key) {
                case 'ArrowDown':
                    event.preventDefault();
                    this.selectedSuggestionIndex = Math.min(
                        this.selectedSuggestionIndex + 1,
                        this.suggestions.length - 1
                    );
                    break;
                case 'ArrowUp':
                    event.preventDefault();
                    this.selectedSuggestionIndex = Math.max(this.selectedSuggestionIndex - 1, -1);
                    break;
                case 'Enter':
                    if (this.selectedSuggestionIndex >= 0) {
                        event.preventDefault();
                        this.selectSuggestion(this.suggestions[this.selectedSuggestionIndex]);
                    }
                    break;
                case 'Escape':
                    this.showSuggestions = false;
                    this.selectedSuggestionIndex = -1;
                    break;
            }
        },

        /**
         * Hide suggestions when clicking outside
         */
        hideSuggestions() {
            // Small timeout to allow click events on suggestions to process
            setTimeout(() => {
                this.showSuggestions = false;
                this.selectedSuggestionIndex = -1;
            }, 200);
        },

        /**
         * Clear search results
         */
        clearResults() {
            this.results = [];
            this.searchPerformed = false;
            this.error = null;

            // Clear URL query parameter
            const newUrl = new URL(window.location);
            newUrl.searchParams.delete('q');
            window.history.pushState({}, '', newUrl);
        },

        /**
         * View detailed execution history for a test case
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
            const total = this.detailsData?.pagination?.total || 0;
            if (total === 0) return 0;
            return this.detailsOffset + 1;
        },

        /**
         * Get pagination end index
         */
        getPaginationEnd() {
            const total = this.detailsData?.pagination?.total || 0;
            if (total === 0) return 0;
            return Math.min(this.detailsOffset + this.detailsLimit, total);
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
         * Format date
         */
        formatDate(dateString) {
            if (!dateString) return 'N/A';
            const date = new Date(dateString);
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        },

        /**
         * Calculate coverage percentage for a priority
         */
        calculateCoverage(priorityStats) {
            if (!priorityStats || priorityStats.total === 0) {
                return '0%';
            }
            const coverage = (priorityStats.with_history / priorityStats.total) * 100;
            return coverage.toFixed(1) + '%';
        }
    };
}
