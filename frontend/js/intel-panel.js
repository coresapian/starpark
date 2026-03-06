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
        this.gaugeCoverage = document.getElementById('gauge-coverage');
        this.gaugeSnr = document.getElementById('gauge-snr');
        this.gaugeTrack = document.getElementById('gauge-track');
        this.gaugeCoverageValue = document.getElementById('gauge-coverage-value');
        this.gaugeSnrValue = document.getElementById('gauge-snr-value');
        this.gaugeTrackValue = document.getElementById('gauge-track-value');
        this.dialDrift = document.getElementById('dial-drift');
        this.dialLock = document.getElementById('dial-lock');
        this.dialNoise = document.getElementById('dial-noise');
        this.dialDriftValue = document.getElementById('dial-drift-value');
        this.dialLockValue = document.getElementById('dial-lock-value');
        this.dialNoiseValue = document.getElementById('dial-noise-value');
    }

    /**
     * Initialize panel.
     */
    init() {
        this._setGauge(this.gaugeCoverage, this.gaugeCoverageValue, 0, '--%');
        this._setGauge(this.gaugeSnr, this.gaugeSnrValue, 0, '-- dB');
        this._setGauge(this.gaugeTrack, this.gaugeTrackValue, 0, '--');
        this._setDial(this.dialDrift, this.dialDriftValue, 0, '--%');
        this._setDial(this.dialLock, this.dialLockValue, 0, '--%');
        this._setDial(this.dialNoise, this.dialNoiseValue, 0, '--%');
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
        this.updateInstrumentCluster(data);
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

    /**
     * Update animated gauge and dial readouts.
     * @param {Object} data
     */
    updateInstrumentCluster(data = {}) {
        const visibility = data.visibility || {};
        const satellites = Array.isArray(data.satellites) ? data.satellites : [];

        const fallbackVisible = satellites.filter((sat) => {
            const isVisible = sat.visible ?? sat.is_visible ?? false;
            const isObstructed = sat.obstructed ?? sat.is_obstructed ?? false;
            return Boolean(isVisible) && !Boolean(isObstructed);
        }).length;
        const fallbackObstructed = satellites.filter((sat) => {
            const isObstructed = sat.obstructed ?? sat.is_obstructed ?? false;
            return Boolean(isObstructed);
        }).length;

        const total = Number(visibility.total_satellites ?? satellites.length ?? 0);
        const visible = Number(visibility.visible_satellites ?? fallbackVisible);
        const obstructed = Number(visibility.obstructed_satellites ?? fallbackObstructed);
        const coveragePct = total > 0 ? (visible / total) * 100 : 0;

        const snrValues = satellites
            .map((sat) => Number(sat.snr))
            .filter((value) => Number.isFinite(value));
        const avgSnr = snrValues.length > 0
            ? snrValues.reduce((sum, value) => sum + value, 0) / snrValues.length
            : 0;

        const trackLoadPct = Math.min(100, (total / 24) * 100);
        const driftPct = total > 0 ? Math.min(100, (obstructed / total) * 100) : 0;
        const lockPct = Math.max(0, Math.min(100, coveragePct * 0.75 + Math.min(100, avgSnr * 2) * 0.25));
        const noisePct = Math.max(0, Math.min(100, 100 - Math.min(100, avgSnr * 2)));
        const hasTelemetry = total > 0 || snrValues.length > 0;

        this._setGauge(
            this.gaugeCoverage,
            this.gaugeCoverageValue,
            coveragePct,
            hasTelemetry ? `${Math.round(coveragePct)}%` : '--%'
        );
        this._setGauge(
            this.gaugeSnr,
            this.gaugeSnrValue,
            Math.min(100, avgSnr * 2),
            hasTelemetry ? `${Math.round(avgSnr)} dB` : '-- dB'
        );
        this._setGauge(
            this.gaugeTrack,
            this.gaugeTrackValue,
            trackLoadPct,
            hasTelemetry ? `${total}` : '--'
        );

        this._setDial(this.dialDrift, this.dialDriftValue, driftPct, hasTelemetry ? `${Math.round(driftPct)}%` : '--%');
        this._setDial(this.dialLock, this.dialLockValue, lockPct, hasTelemetry ? `${Math.round(lockPct)}%` : '--%');
        this._setDial(this.dialNoise, this.dialNoiseValue, noisePct, hasTelemetry ? `${Math.round(noisePct)}%` : '--%');
    }

    _setGauge(element, valueElement, percent, text) {
        if (!element || !valueElement) return;
        const clamped = Math.max(0, Math.min(100, Number(percent) || 0));
        const fillAngle = 260 * (clamped / 100);
        const needleAngle = -130 + fillAngle;
        element.style.setProperty('--fill-angle', `${fillAngle.toFixed(2)}deg`);
        element.style.setProperty('--needle-angle', `${needleAngle.toFixed(2)}deg`);
        valueElement.textContent = text;
    }

    _setDial(element, valueElement, percent, text) {
        if (!element || !valueElement) return;
        const clamped = Math.max(0, Math.min(100, Number(percent) || 0));
        const angle = -120 + (clamped * 2.4);
        element.style.setProperty('--dial-angle', `${angle.toFixed(2)}deg`);
        valueElement.textContent = text;
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
