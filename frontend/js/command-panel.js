/**
 * LinkSpot Command Panel
 * Controls tab switching and sidebar command helpers.
 */
class CommandPanel {
    constructor() {
        this.app = null;
        this.analysisTabBtn = document.querySelector('.sidebar-tab[data-tab="analysis"]');
        this.missionTabBtn = document.querySelector('.sidebar-tab[data-tab="mission"]');
        this.analysisPanel = document.getElementById('tab-analysis');
        this.missionPanel = document.getElementById('tab-mission');
        this.terminalField = document.getElementById('terminal-cmd');
        this.waypointList = document.getElementById('waypoint-list');
        this.waypointSection = document.getElementById('waypoint-list-section');
        this.missionOrigin = document.getElementById('mission-origin');
        this.missionDestination = document.getElementById('mission-destination');
        this.computeRouteBtn = document.getElementById('compute-route-btn');
    }

    /**
     * Bind panel behavior.
     * @param {Object} app
     */
    init(app) {
        this.app = app;
        // TODO: Keep mission panel state in sync with map/search state via explicit model object.
        // TODO: Remove legacy direct DOM coupling after mission state store migration is complete.

        if (this.analysisTabBtn) {
            this.analysisTabBtn.addEventListener('click', () => this.switchTab('analysis'));
        }
        if (this.missionTabBtn) {
            this.missionTabBtn.addEventListener('click', () => this.switchTab('mission'));
        }

        if (this.terminalField) {
            this.terminalField.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter') return;
                const cmd = this.terminalField.value.trim();
                this.terminalField.value = '';
                this.handleTerminalInput(cmd);
            });
        }

        if (this.computeRouteBtn) {
            this.computeRouteBtn.addEventListener('click', () => {
                if (!this.app) return;
                const destinationText = this.missionDestination
                    ? this.missionDestination.value.trim()
                    : '';

                if (!destinationText) {
                    this.app.showToast('Set a mission destination first', 'warning');
                    return;
                }
                // TODO: Handle destination field as JSON coordinates with explicit validation.

                if (this.missionOrigin && this.missionOrigin.value.trim()) {
                    const match = this.missionOrigin.value.trim()
                        .match(/^\\s*(-?\\d+(?:\\.\\d+)?)\\s*,\\s*(-?\\d+(?:\\.\\d+)?)\\s*$/);
                    if (match) {
                        this.app.state.routeOrigin = {
                            lat: Number.parseFloat(match[1]),
                            lon: Number.parseFloat(match[2])
                        };
                    }
                }

                const searchInput = document.getElementById('search-input');
                if (searchInput) searchInput.value = destinationText;
                this.app.updateRoutePlanButtonState();
                this.app.planRouteFromSearch();
            });
        }
    }

    /**
     * Toggle active sidebar tab.
     * @param {'analysis'|'mission'} tab
     */
    switchTab(tab) {
        const mission = tab === 'mission';

        if (this.analysisTabBtn) this.analysisTabBtn.classList.toggle('active', !mission);
        if (this.missionTabBtn) this.missionTabBtn.classList.toggle('active', mission);
        if (this.analysisPanel) this.analysisPanel.classList.toggle('hidden', mission);
        if (this.missionPanel) this.missionPanel.classList.toggle('hidden', !mission);
    }

    /**
     * Update quick stat blocks if present.
     * @param {Object} data
     */
    updateStats(data = {}) {
        this._setText('stat-visible', `${data.visible_satellites ?? '--'}`);
        this._setText('stat-obstructed', `${data.obstructed_satellites ?? '--'}`);

        if (Number.isFinite(data.coverage_pct)) {
            this._setText('stat-coverage', `${Math.round(data.coverage_pct)}%`);
        }

        if (data.status) {
            this._setText('stat-zone', String(data.status).toUpperCase());
        }
    }

    /**
     * Render waypoint list in mission panel.
     * @param {Array} waypoints
     */
    populateWaypoints(waypoints = []) {
        if (!this.waypointList || !this.waypointSection) return;
        // TODO: Keep waypoint list scroll position when refreshing to avoid disorienting mission operators.

        if (!Array.isArray(waypoints) || waypoints.length === 0) {
            this.waypointList.innerHTML = '<div class="waypoint-empty">No waypoints suggested</div>';
            this.waypointSection.style.display = 'block';
            return;
        }

        this.waypointList.innerHTML = waypoints.map((wp) => {
            const etaMin = wp.eta_seconds ? Math.round(wp.eta_seconds / 60) : 0;
            const zone = wp.zone || 'BLOCKED';
            return (
                `<button class="waypoint-row" data-lat="${wp.lat}" data-lon="${wp.lon}">` +
                `<span class="waypoint-id">${wp.id}</span>` +
                `<span class="waypoint-name">${this._escape(wp.name || 'Waypoint')}</span>` +
                `<span class="waypoint-meta">${zone} • ETA ${etaMin}m</span>` +
                '</button>'
            );
        }).join('');

        this.waypointList.querySelectorAll('.waypoint-row').forEach((row) => {
            row.addEventListener('click', () => {
                if (!this.app || !this.app.state.map) return;
                const lat = Number.parseFloat(row.dataset.lat);
                const lon = Number.parseFloat(row.dataset.lon);
                if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
                this.app.state.map.setView([lat, lon], 16);
            });
        });

        this.waypointSection.style.display = 'block';
    }

    /**
     * Trigger search flow.
     * @param {string} query
     */
    handleSearch(query) {
        if (!this.app || !query) return;
        this.app.searchLocation(query);
    }

    /**
     * Parse command terminal input as coordinates.
     * @param {string} cmd
     */
    handleTerminalInput(cmd) {
        if (!this.app || !cmd) return;

        const match = cmd.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
        if (!match) {
            this.app.showToast('Terminal expects "lat,lon" coordinates', 'warning');
            return;
        }

        const lat = Number.parseFloat(match[1]);
        const lon = Number.parseFloat(match[2]);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
            this.app.showToast('Invalid coordinate command', 'warning');
            return;
        }

        this.app.selectSearchResult(lat, lon, `${lat.toFixed(5)}, ${lon.toFixed(5)}`);
    }

    _setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    _escape(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

if (typeof window !== 'undefined') {
    window.CommandPanel = CommandPanel;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { CommandPanel };
}
