/**
 * LinkSpot Intel Panel
 * Renders analysis, data quality, mission brief, and satellite list.
 */
class IntelPanel {
    constructor() {
        this.analysisStats = document.getElementById('analysis-stats');
        this.satelliteList = document.getElementById('satellite-list');
        this.missionBrief = document.getElementById('mission-brief');
        this.missionBriefSection = document.getElementById('mission-brief-section');
        this.dataQualityDisplay = document.getElementById('data-quality-display');
    }

    /**
     * Initialize panel.
     */
    init() {
        return true;
    }

    /**
     * Render analysis details.
     * @param {Object} data
     */
    updateAnalysis(data) {
        if (!data || !this.analysisStats) return;
        // TODO: Remove legacy visibility key support (`is_visible`, `is_obstructed`) once all payloads use canonical `visible`/`obstructed`.

        const visibility = data.visibility || {};
        const total = Number(visibility.total_satellites || 0);
        const visible = Number(visibility.visible_satellites || 0);
        const obstructed = Number(visibility.obstructed_satellites || 0);
        const coverage = total > 0 ? Math.round((visible / total) * 100) : 0;

        this.analysisStats.innerHTML = [
            this._statBlock('VISIBLE', visible),
            this._statBlock('BLOCKED', obstructed),
            this._statBlock('TOTAL', total),
            this._statBlock('COVERAGE', `${coverage}%`)
        ].join('');

        this.updateSatelliteList(data.satellites || []);
        this.updateDataQuality(data.data_quality || null);
    }

    /**
     * Render mission summary text.
     * @param {Object} summary
     */
    updateMissionBrief(summary) {
        if (!this.missionBrief || !summary) return;

        const distanceKm = (Number(summary.total_distance_m || 0) / 1000).toFixed(1);
        const durationMin = Math.round(Number(summary.total_duration_s || 0) / 60);
        const coverage = Number(summary.route_coverage_pct || 0).toFixed(1);

        this.missionBrief.innerHTML = (
            `<div><strong>Distance:</strong> ${distanceKm} km</div>` +
            `<div><strong>ETA:</strong> ${durationMin} min</div>` +
            `<div><strong>Coverage:</strong> ${coverage}%</div>` +
            `<div><strong>Waypoints:</strong> ${summary.num_waypoints || 0}</div>`
        );

        if (this.missionBriefSection) {
            this.missionBriefSection.style.display = 'block';
        }
    }

    /**
     * Render data-quality chips.
     * @param {Object|null} dq
     */
    updateDataQuality(dq) {
        if (!this.dataQualityDisplay) return;

        if (!dq) {
            this.dataQualityDisplay.innerHTML = '<span class="dq-chip">No data quality details</span>';
            return;
        }

        const warnings = Array.isArray(dq.warnings) ? dq.warnings : [];
        const warningHtml = warnings.length > 0
            ? `<div class="dq-warnings">${warnings.map((w) => `<div>${this._escape(w)}</div>`).join('')}</div>`
            : '';

        this.dataQualityDisplay.innerHTML = (
            `<div class="dq-grid">` +
            `<span class="dq-chip">BLD: ${this._escape(String(dq.buildings || 'unknown'))}</span>` +
            `<span class="dq-chip">TER: ${this._escape(String(dq.terrain || 'unknown'))}</span>` +
            `<span class="dq-chip">SAT: ${this._escape(String(dq.satellites || 'unknown'))}</span>` +
            `</div>` +
            warningHtml
        );
    }

    /**
     * Render satellite list entries.
     * @param {Array} satellites
     */
    updateSatelliteList(satellites) {
        if (!this.satelliteList) return;

        const visible = (Array.isArray(satellites) ? satellites : [])
            .filter((sat) => {
                const isVisible = sat.visible ?? sat.is_visible ?? false;
                const isObstructed = sat.obstructed ?? sat.is_obstructed ?? false;
                return Boolean(isVisible) && !Boolean(isObstructed);
            })
            .slice(0, 24);

        if (visible.length === 0) {
            this.satelliteList.innerHTML = '<li class="satellite-empty">No visible satellites</li>';
            return;
        }

        this.satelliteList.innerHTML = visible.map((sat) => {
            const elev = Number.isFinite(Number(sat.elevation)) ? `${Math.round(Number(sat.elevation))}°` : '--';
            const snr = sat.snr != null ? `${sat.snr} dB` : '--';
            return (
                '<li class="satellite-item">' +
                `<span class="satellite-name">${this._escape(sat.name || sat.id || 'SAT')}</span>` +
                `<span class="satellite-info">${elev} • ${snr}</span>` +
                '</li>'
            );
        }).join('');
    }

    _statBlock(label, value) {
        return `<div class="stat-item"><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`;
    }

    _escape(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

if (typeof window !== 'undefined') {
    window.IntelPanel = IntelPanel;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { IntelPanel };
}
