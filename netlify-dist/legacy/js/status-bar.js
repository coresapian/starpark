/**
 * LinkSpot Status Bar
 * Updates LEDs, GPS state, and UTC clock.
 */
class StatusBar {
    constructor() {
        this.ledMap = {
            backend: document.getElementById('led-backend'),
            buildings: document.getElementById('led-buildings'),
            terrain: document.getElementById('led-terrain'),
            satellites: document.getElementById('led-satellites'),
            routing: document.getElementById('led-routing')
        };
        this.gpsEl = document.getElementById('gps-status');
        this.clockEl = document.getElementById('utc-clock');
        this.clockTimer = null;
    }

    /**
     * Set LED status.
     * @param {string} id
     * @param {'green'|'amber'|'red'|'unknown'} status
     */
    updateLED(id, status = 'unknown') {
        const led = this.ledMap[id];
        if (!led) return;
        led.dataset.status = status;
    }

    /**
     * Set GPS fix text.
     * @param {boolean} fix
     */
    updateGPS(fix) {
        if (!this.gpsEl) return;
        this.gpsEl.textContent = fix ? 'GPS FIX' : 'NO FIX';
        this.gpsEl.dataset.status = fix ? 'green' : 'amber';
    }

    /**
     * Start ticking UTC clock.
     */
    startClock() {
        if (this.clockTimer) return;

        const tick = () => {
            if (!this.clockEl) return;
            const now = new Date();
            const hh = String(now.getUTCHours()).padStart(2, '0');
            const mm = String(now.getUTCMinutes()).padStart(2, '0');
            const ss = String(now.getUTCSeconds()).padStart(2, '0');
            this.clockEl.textContent = `${hh}:${mm}:${ss}Z`;
        };

        tick();
        this.clockTimer = window.setInterval(tick, 1000);
    }

    /**
     * Stop UTC clock.
     */
    stopClock() {
        if (!this.clockTimer) return;
        window.clearInterval(this.clockTimer);
        this.clockTimer = null;
    }

    /**
     * Map API data quality into LEDs.
     * @param {Object|null|undefined} dq
     */
    updateFromDataQuality(dq) {
        if (!dq) return;

        const buildingsStatus = dq.buildings === 'full'
            ? 'green'
            : (dq.buildings === 'partial' ? 'amber' : 'red');

        const terrainStatus = dq.terrain === 'full' ? 'green' : 'amber';

        const satellitesStatus = dq.satellites === 'live'
            ? 'green'
            : (dq.satellites === 'cached' ? 'amber' : 'red');

        this.updateLED('buildings', buildingsStatus);
        this.updateLED('terrain', terrainStatus);
        this.updateLED('satellites', satellitesStatus);
    }
}

if (typeof window !== 'undefined') {
    window.StatusBar = StatusBar;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { StatusBar };
}
