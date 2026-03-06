/**
 * LinkSpot Effects Engine
 * Handles boot, glitch, cascade, and signal-loss overlays.
 */
class EffectsEngine {
    /**
     * @param {Object} options
     * @param {HTMLElement|null} [options.shell]
     * @param {HTMLElement|null} [options.signalLost]
     */
    constructor(options = {}) {
        this.shell = options.shell || document.getElementById('app-shell');
        this.signalLostOverlay = options.signalLost || document.getElementById('signal-lost');
    }

    /**
     * Run a short panel boot sequence.
     * @returns {Promise<void>}
     */
    async bootSequence() {
        if (!this.shell) return;

        this.shell.classList.add('boot-sequence');
        await this._delay(120);
        this.shell.classList.add('boot-flicker');
        await this._delay(280);
        this.shell.classList.remove('boot-flicker');
        this.shell.classList.add('boot-online');
        await this._delay(220);
        this.shell.classList.remove('boot-sequence');
    }

    /**
     * Animate a numeric roll-up effect.
     * @param {HTMLElement|null} element
     * @param {number|string} targetValue
     * @param {number} durationMs
     */
    dataCascade(element, targetValue, durationMs = 420) {
        if (!element) return;

        const parsed = Number.parseFloat(String(targetValue).replace(/[^0-9.-]/g, ''));
        if (!Number.isFinite(parsed)) {
            element.textContent = String(targetValue);
            return;
        }

        const start = performance.now();
        const from = 0;
        const suffix = typeof targetValue === 'string'
            ? String(targetValue).replace(/[0-9.,\-]/g, '')
            : '';

        const tick = (now) => {
            const t = Math.min(1, (now - start) / durationMs);
            const eased = 1 - Math.pow(1 - t, 3);
            const value = from + (parsed - from) * eased;
            element.textContent = `${Math.round(value)}${suffix}`;
            if (t < 1) requestAnimationFrame(tick);
        };

        requestAnimationFrame(tick);
    }

    /**
     * Apply a brief glitch pulse.
     * @param {HTMLElement|null} element
     */
    glitch(element) {
        if (!element) return;
        element.classList.add('fx-glitch');
        window.setTimeout(() => element.classList.remove('fx-glitch'), 260);
    }

    /**
     * Show or hide full-screen signal-lost overlay.
     * @param {boolean} show
     */
    signalLost(show) {
        if (!this.signalLostOverlay) return;
        this.signalLostOverlay.classList.toggle('hidden', !show);
    }

    _delay(ms) {
        return new Promise((resolve) => window.setTimeout(resolve, ms));
    }
}

if (typeof window !== 'undefined') {
    window.EffectsEngine = EffectsEngine;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { EffectsEngine };
}
