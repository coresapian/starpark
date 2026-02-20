/**
 * LinkSpot Sky Plot Visualization
 * Polar sky diagram showing satellite positions and obstructions
 * Canvas-based rendering for high performance
 * @version 1.0.0
 */

/**
 * SkyPlot class for rendering polar sky diagrams
 * Shows satellite positions and obstruction profiles
 */
class SkyPlot {
    /**
     * Create a SkyPlot instance
     * @param {HTMLCanvasElement} canvas - The canvas element to render on
     * @param {Object} options - Configuration options
     * @param {number} options.width - Canvas width (default: canvas width)
     * @param {number} options.height - Canvas height (default: canvas height)
     * @param {number} options.padding - Padding around the plot (default: 20)
     * @param {string} options.satelliteColor - Color for visible satellites
     * @param {string} options.obstructedColor - Color for obstructed satellites
     * @param {string} options.obstructionFill - Fill color for obstruction profile
     * @param {string} options.gridColor - Color for grid lines
     * @param {string} options.textColor - Color for labels
     * @param {'low'|'medium'|'max'} [options.fxIntensity] - Render FX profile
     */
    constructor(canvas, options = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        
        // Set canvas size with device pixel ratio for sharp rendering
        this.dpr = window.devicePixelRatio || 1;
        this.width = (options.width || canvas.width || 280) * this.dpr;
        this.height = (options.height || canvas.height || 280) * this.dpr;
        
        // Adjust canvas for high DPI displays
        canvas.width = this.width;
        canvas.height = this.height;
        canvas.style.width = `${this.width / this.dpr}px`;
        canvas.style.height = `${this.height / this.dpr}px`;
        
        // Configuration
        this.padding = (options.padding || 20) * this.dpr;
        this.radius = Math.min(this.width, this.height) / 2 - this.padding;
        this.centerX = this.width / 2;
        this.centerY = this.height / 2;
        
        // Colors
        this.colors = {
            satellite: options.satelliteColor || '#2dd4bf',
            obstructed: options.obstructedColor || '#6c757d',
            obstructionFill: options.obstructionFill || 'rgba(239, 68, 68, 0.22)',
            obstructionStroke: options.obstructionStroke || 'rgba(248, 113, 113, 0.8)',
            grid: options.gridColor || 'rgba(45, 212, 191, 0.24)',
            text: options.textColor || '#93c5fd',
            horizon: options.horizonColor || 'rgba(34, 197, 94, 0.72)',
            cardinal: options.cardinalColor || '#e2e8f0',
            sweep: options.sweepColor || 'rgba(34, 211, 238, 0.26)',
            threat: options.threatColor || 'rgba(248, 113, 113, 0.5)',
            dial: options.dialColor || 'rgba(34, 211, 238, 0.42)',
            lock: options.lockColor || 'rgba(186, 230, 253, 0.7)'
        };
        
        // Data storage
        this.satellites = [];
        this.obstructions = [];
        this.horizonElevation = 10; // Minimum elevation for visibility
        this.trailHistory = new Map();
        this.maxTrailPoints = 16;
        this.trailMaxAgeMs = 3 * 60 * 1000;
        this._cachedObstructionKey = null;
        this._sortedObstructions = [];

        // Animation
        this.animationId = null;
        this.isAnimating = false;
        this.sweepAngle = 0;
        this.sweepAnimationId = null;
        this.sweepActive = true;
        this._lastSweepTick = 0;
        this.fxIntensity = 'medium';
        this.fxProfile = {
            speedMultiplier: 1,
            alphaMultiplier: 1,
            detailMultiplier: 1
        };
        this._visibilityHandler = () => {
            if (document.hidden) {
                this.stopSweep();
            } else if (!this.sweepAnimationId) {
                this.startSweep();
            }
        };
        this.setFxIntensity(options.fxIntensity || 'medium');
        document.addEventListener('visibilitychange', this._visibilityHandler);
        this.startSweep();
    }
    
    /**
     * Clear the canvas
     * @private
     */
    clear() {
        this.ctx.clearRect(0, 0, this.width, this.height);
    }
    
    /**
     * Convert azimuth/elevation to canvas coordinates
     * @private
     * @param {number} azimuth - Azimuth in degrees (0-360, 0 = North)
     * @param {number} elevation - Elevation in degrees (0-90, 90 = zenith)
     * @returns {Object} {x, y} canvas coordinates
     */
    polarToCartesian(azimuth, elevation) {
        // Convert to radians
        const azimuthRad = (azimuth - 90) * (Math.PI / 180); // -90 to align North up
        const elevationRad = elevation * (Math.PI / 180);
        
        // In sky plot, zenith is at center, horizon at edge
        // Distance from center is proportional to (90 - elevation)
        const distance = (90 - elevation) / 90 * this.radius;
        
        return {
            x: this.centerX + distance * Math.cos(azimuthRad),
            y: this.centerY + distance * Math.sin(azimuthRad)
        };
    }
    
    /**
     * Convert canvas coordinates to azimuth/elevation
     * @private
     * @param {number} x - Canvas X coordinate
     * @param {number} y - Canvas Y coordinate
     * @returns {Object} {azimuth, elevation} in degrees
     */
    cartesianToPolar(x, y) {
        const dx = x - this.centerX;
        const dy = y - this.centerY;
        
        // Distance from center
        const distance = Math.sqrt(dx * dx + dy * dy);
        
        // Elevation: 90 at center, 0 at edge
        const elevation = Math.max(0, 90 - (distance / this.radius * 90));
        
        // Azimuth
        let azimuth = Math.atan2(dy, dx) * (180 / Math.PI) + 90;
        if (azimuth < 0) azimuth += 360;
        if (azimuth >= 360) azimuth -= 360;
        
        return { azimuth, elevation };
    }
    
    /**
     * Draw the grid (concentric circles and radial lines)
     * @private
     */
    drawGrid() {
        const ctx = this.ctx;
        
        ctx.strokeStyle = this.colors.grid;
        ctx.lineWidth = 1 * this.dpr;
        ctx.setLineDash([2 * this.dpr, 4 * this.dpr]);
        
        // Draw elevation circles (30°, 60°)
        [30, 60].forEach(elevation => {
            const radius = (90 - elevation) / 90 * this.radius;
            ctx.beginPath();
            ctx.arc(this.centerX, this.centerY, radius, 0, Math.PI * 2);
            ctx.stroke();
            
            // Label
            ctx.fillStyle = this.colors.text;
            ctx.font = `${10 * this.dpr}px "JetBrains Mono", monospace`;
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(`${elevation}°`, this.centerX + radius + 4 * this.dpr, this.centerY);
        });
        
        // Draw horizon circle
        ctx.strokeStyle = this.colors.horizon;
        ctx.lineWidth = 2 * this.dpr;
        ctx.beginPath();
        ctx.arc(this.centerX, this.centerY, this.radius, 0, Math.PI * 2);
        ctx.stroke();
        
        // Draw cardinal direction lines
        ctx.strokeStyle = this.colors.grid;
        ctx.lineWidth = 1 * this.dpr;
        ctx.setLineDash([]);
        
        const directions = [
            { angle: 0, label: 'N' },
            { angle: 90, label: 'E' },
            { angle: 180, label: 'S' },
            { angle: 270, label: 'W' }
        ];
        
        directions.forEach(({ angle, label }) => {
            const start = this.polarToCartesian(angle, 0);
            const end = this.polarToCartesian(angle, 90);
            
            ctx.beginPath();
            ctx.moveTo(start.x, start.y);
            ctx.lineTo(end.x, end.y);
            ctx.stroke();
            
            // Cardinal labels
            const labelPos = this.polarToCartesian(angle, -10);
            ctx.fillStyle = this.colors.cardinal;
            ctx.font = `bold ${12 * this.dpr}px "JetBrains Mono", monospace`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, labelPos.x, labelPos.y);
        });
        
        // Draw azimuth tick marks
        for (let az = 0; az < 360; az += 30) {
            if (az % 90 === 0) continue; // Skip cardinal directions
            
            const outer = this.polarToCartesian(az, 0);
            const inner = this.polarToCartesian(az, 5);
            
            ctx.beginPath();
            ctx.moveTo(outer.x, outer.y);
            ctx.lineTo(inner.x, inner.y);
            ctx.stroke();
        }
    }

    /**
     * Draw rotating dial ticks around the horizon ring.
     * @private
     */
    drawReticleDial() {
        const ctx = this.ctx;
        const outerRadius = this.radius + 8 * this.dpr;
        const phase = (this.sweepAngle - 90) * Math.PI / 180;
        const pulse = 0.2 + (Math.sin(Date.now() / 360) + 1) * 0.14;

        ctx.save();

        ctx.strokeStyle = `rgba(34, 211, 238, ${0.18 + pulse})`;
        ctx.lineWidth = 1 * this.dpr;
        ctx.setLineDash([4 * this.dpr, 5 * this.dpr]);
        ctx.beginPath();
        ctx.arc(this.centerX, this.centerY, outerRadius, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);

        for (let i = 0; i < 16; i += 1) {
            const angle = phase + (i * Math.PI / 8);
            const tick = (i % 4 === 0 ? 12 : 7) * this.dpr;
            const x1 = this.centerX + (outerRadius - tick) * Math.cos(angle);
            const y1 = this.centerY + (outerRadius - tick) * Math.sin(angle);
            const x2 = this.centerX + (outerRadius + 1.5 * this.dpr) * Math.cos(angle);
            const y2 = this.centerY + (outerRadius + 1.5 * this.dpr) * Math.sin(angle);
            ctx.strokeStyle = i === 0 ? this.colors.lock : this.colors.dial;
            ctx.lineWidth = (i === 0 ? 2 : 1) * this.dpr;
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();
        }

        ctx.restore();
    }
    
    /**
     * Draw obstruction profile
     * @private
     */
    drawObstructions() {
        if (!this.obstructions || this.obstructions.length === 0) return;
        
        const ctx = this.ctx;
        const key = JSON.stringify(this.obstructions.map((obs) => [obs.azimuth, obs.elevation]));
        if (key !== this._cachedObstructionKey) {
            this._cachedObstructionKey = key;
            this._sortedObstructions = [...this.obstructions].sort((a, b) => a.azimuth - b.azimuth);
        }
        const sorted = this._sortedObstructions;
        
        // Create path for obstruction silhouette
        ctx.beginPath();
        
        // Start from center (zenith)
        ctx.moveTo(this.centerX, this.centerY);
        
        // Draw to each obstruction point
        sorted.forEach((obs, index) => {
            const pos = this.polarToCartesian(obs.azimuth, obs.elevation);
            if (index === 0) {
                ctx.lineTo(pos.x, pos.y);
            } else {
                ctx.lineTo(pos.x, pos.y);
            }
        });
        
        // Close path back to center
        ctx.lineTo(this.centerX, this.centerY);
        
        // Fill obstruction area
        ctx.fillStyle = this.colors.obstructionFill;
        ctx.fill();
        
        // Stroke obstruction outline
        ctx.strokeStyle = this.colors.obstructionStroke;
        ctx.lineWidth = 2 * this.dpr;
        ctx.stroke();
    }

    /**
     * Draw pulsing threat-ring sectors where obstruction elevation is significant.
     * @private
     */
    drawThreatRings() {
        if (!this.obstructions || this.obstructions.length === 0) return;

        const ctx = this.ctx;
        const pulse = (0.35 + (Math.sin(Date.now() / 260) + 1) * 0.2) * this.fxProfile.alphaMultiplier;
        let rendered = 0;
        const maxThreatRings = Math.max(24, Math.round(96 * this.fxProfile.detailMultiplier));

        this.obstructions.forEach((obs, index) => {
            if (!Number.isFinite(obs.elevation) || obs.elevation < 20) return;
            if (rendered >= maxThreatRings) return;
            rendered += 1;

            const outerRadius = (90 - Math.max(0, obs.elevation - 8)) / 90 * this.radius;
            const innerRadius = (90 - Math.min(90, obs.elevation + 8)) / 90 * this.radius;
            const start = (obs.azimuth - 5 - 90) * Math.PI / 180;
            const end = (obs.azimuth + 5 - 90) * Math.PI / 180;

            ctx.save();
            ctx.fillStyle = `rgba(248, 113, 113, ${Math.min(0.65, pulse + 0.06)})`;
            ctx.strokeStyle = this.colors.threat;
            ctx.lineWidth = (1.1 + 0.4 * this.fxProfile.detailMultiplier) * this.dpr;
            ctx.setLineDash(index % 2 === 0 ? [2 * this.dpr, 3 * this.dpr] : [1 * this.dpr, 4 * this.dpr]);

            ctx.beginPath();
            ctx.arc(this.centerX, this.centerY, outerRadius, start, end);
            ctx.arc(this.centerX, this.centerY, innerRadius, end, start, true);
            ctx.closePath();
            ctx.fill();
            ctx.stroke();
            ctx.restore();
        });
    }

    /**
     * Draw short projected trail arcs for visible satellites.
     * @private
     */
    drawSatelliteTrails() {
        if (!this.satellites || this.satellites.length === 0) return;

        const ctx = this.ctx;
        this.satellites.forEach((sat) => {
            const key = sat.id || sat.name;
            if (!key || !this.trailHistory.has(key)) return;
            const trail = this.trailHistory.get(key);
            if (!trail || trail.length < 2) return;

            ctx.save();
            ctx.strokeStyle = `rgba(45, 212, 191, ${0.35 * this.fxProfile.alphaMultiplier})`;
            ctx.lineWidth = 1.4 * this.dpr;
            ctx.beginPath();

            trail.forEach((point, idx) => {
                const pos = this.polarToCartesian(point.azimuth, point.elevation);
                if (idx === 0) ctx.moveTo(pos.x, pos.y);
                else ctx.lineTo(pos.x, pos.y);
            });

            ctx.stroke();
            ctx.restore();
        });
    }

    /**
     * Draw dynamic link arcs for satellites near current sweep heading.
     * @private
     */
    drawLinkArcs() {
        if (!this.satellites || this.satellites.length === 0) return;

        const ctx = this.ctx;
        const maxLinks = Math.max(8, Math.round(20 * this.fxProfile.detailMultiplier));
        const lockCone = 24 + (24 * this.fxProfile.detailMultiplier);
        const visible = this.satellites
            .filter((sat) => sat.visible && !sat.obstructed)
            .slice(0, maxLinks);

        visible.forEach((sat, index) => {
            const delta = Math.abs((((sat.azimuth - this.sweepAngle) % 360) + 540) % 360 - 180);
            if (delta > lockCone) return;

            const strength = 1 - (delta / lockCone);
            const pos = this.polarToCartesian(sat.azimuth, sat.elevation);
            const controlX = (this.centerX + pos.x) / 2;
            const controlY = (this.centerY + pos.y) / 2 - (8 + (index % 4) * 2) * this.dpr;

            ctx.save();
            ctx.strokeStyle = `rgba(56, 189, 248, ${(0.08 + strength * 0.34) * this.fxProfile.alphaMultiplier})`;
            ctx.lineWidth = (1 + strength * 1.3 * this.fxProfile.detailMultiplier) * this.dpr;
            ctx.setLineDash(index % 2 === 0 ? [3 * this.dpr, 4 * this.dpr] : []);
            ctx.beginPath();
            ctx.moveTo(this.centerX, this.centerY);
            ctx.quadraticCurveTo(controlX, controlY, pos.x, pos.y);
            ctx.stroke();
            ctx.restore();
        });
    }

    /**
     * Draw rotating radar sweep line.
     * @private
     */
    drawRadarSweep() {
        const ctx = this.ctx;
        const sweepSpread = 8 + (8 * this.fxProfile.detailMultiplier);
        const sweepStart = (this.sweepAngle - sweepSpread - 90) * Math.PI / 180;
        const sweepEnd = (this.sweepAngle - 90) * Math.PI / 180;

        ctx.save();
        const grad = ctx.createRadialGradient(
            this.centerX,
            this.centerY,
            0,
            this.centerX,
            this.centerY,
            this.radius
        );
        grad.addColorStop(0, 'rgba(34, 211, 238, 0)');
        grad.addColorStop(1, `rgba(34, 211, 238, ${Math.min(0.4, 0.22 * this.fxProfile.alphaMultiplier)})`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.moveTo(this.centerX, this.centerY);
        ctx.arc(this.centerX, this.centerY, this.radius, sweepStart, sweepEnd);
        ctx.closePath();
        ctx.fill();

        const end = this.polarToCartesian(this.sweepAngle, 0);
        ctx.strokeStyle = `rgba(34, 211, 238, ${Math.min(0.95, 0.6 + 0.25 * this.fxProfile.alphaMultiplier)})`;
        ctx.lineWidth = (1.4 + (0.8 * this.fxProfile.detailMultiplier)) * this.dpr;
        ctx.beginPath();
        ctx.moveTo(this.centerX, this.centerY);
        ctx.lineTo(end.x, end.y);
        ctx.stroke();
        ctx.restore();
    }
    
    /**
     * Draw satellites
     * @private
     */
    drawSatellites() {
        if (!this.satellites || this.satellites.length === 0) return;
        
        const ctx = this.ctx;
        const now = Date.now();
        
        this.satellites.forEach(sat => {
            const pos = this.polarToCartesian(sat.azimuth, sat.elevation);
            const isVisible = sat.visible && !sat.obstructed && sat.elevation >= this.horizonElevation;
            
            // Draw satellite marker
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, 6 * this.dpr, 0, Math.PI * 2);
            ctx.fillStyle = isVisible ? this.colors.satellite : this.colors.obstructed;
            ctx.fill();
            
            // Add glow effect for visible satellites
            if (isVisible) {
                const pulseRadius = (9 + ((Math.sin((now / 280) + sat.azimuth) + 1) * 1.6 * this.fxProfile.detailMultiplier)) * this.dpr;
                ctx.beginPath();
                ctx.arc(pos.x, pos.y, pulseRadius, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(45, 212, 191, ${Math.min(0.55, 0.28 * this.fxProfile.alphaMultiplier)})`;
                ctx.fill();
            }
            
            // Draw satellite ID label
            ctx.fillStyle = this.colors.text;
            ctx.font = `${9 * this.dpr}px "JetBrains Mono", monospace`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText(
                sat.id || sat.name?.substring(0, 3) || '?',
                pos.x,
                pos.y - 10 * this.dpr
            );
            
            // Draw elevation line for obstructed satellites
            if (sat.obstructed) {
                ctx.strokeStyle = this.colors.obstructed;
                ctx.lineWidth = 1 * this.dpr;
                ctx.setLineDash([3 * this.dpr, 3 * this.dpr]);
                ctx.beginPath();
                ctx.moveTo(pos.x, pos.y);
                const horizonPos = this.polarToCartesian(sat.azimuth, 0);
                ctx.lineTo(horizonPos.x, horizonPos.y);
                ctx.stroke();
                ctx.setLineDash([]);
            }
        });
    }

    /**
     * Draw pulsing zenith marker at center of plot.
     * @private
     */
    drawZenithPulse() {
        const ctx = this.ctx;
        const pulse = (Math.sin(Date.now() / 420) + 1) / 2;
        const radius = (3 + pulse * (2.5 * this.fxProfile.detailMultiplier)) * this.dpr;

        ctx.save();
        ctx.fillStyle = `rgba(165, 243, 252, ${Math.min(0.95, 0.72 + 0.18 * this.fxProfile.alphaMultiplier)})`;
        ctx.beginPath();
        ctx.arc(this.centerX, this.centerY, radius, 0, Math.PI * 2);
        ctx.fill();

        const strokeAlpha = Math.min(0.9, (0.3 + pulse * 0.35) * this.fxProfile.alphaMultiplier);
        ctx.strokeStyle = `rgba(34, 211, 238, ${strokeAlpha})`;
        ctx.lineWidth = 1.4 * this.dpr;
        ctx.beginPath();
        ctx.arc(this.centerX, this.centerY, radius + (6 * this.dpr), 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
    }

    /**
     * Set render effects intensity for radar animation.
     * @param {'low'|'medium'|'max'|string} level
     */
    setFxIntensity(level = 'medium') {
        const normalized = String(level || '').toLowerCase();
        const profiles = {
            low: { speedMultiplier: 0.56, alphaMultiplier: 0.55, detailMultiplier: 0.65 },
            medium: { speedMultiplier: 1, alphaMultiplier: 1, detailMultiplier: 1 },
            max: { speedMultiplier: 1.55, alphaMultiplier: 1.28, detailMultiplier: 1.3 }
        };

        this.fxIntensity = normalized === 'low' || normalized === 'max' ? normalized : 'medium';
        this.fxProfile = profiles[this.fxIntensity];
        this.draw();
    }
    
    /**
     * Draw the complete sky plot
     */
    draw() {
        this.clear();
        this.drawGrid();
        this.drawReticleDial();
        this.drawThreatRings();
        this.drawObstructions();
        this.drawSatelliteTrails();
        this.drawLinkArcs();
        this.drawSatellites();
        this.drawZenithPulse();
        this.drawRadarSweep();
    }
    
    /**
     * Set satellite data and redraw
     * @param {Array} satellites - Array of satellite objects
     * @param {Object} satellites[].id - Satellite ID
     * @param {Object} satellites[].name - Satellite name
     * @param {number} satellites[].azimuth - Azimuth in degrees
     * @param {number} satellites[].elevation - Elevation in degrees
     * @param {boolean} satellites[].visible - Whether satellite is visible
     * @param {boolean} satellites[].obstructed - Whether satellite is obstructed
     */
    setSatellites(satellites) {
        this.satellites = satellites || [];
        this._updateTrailHistory(this.satellites);
        this.draw();
    }
    
    /**
     * Set obstruction data and redraw
     * @param {Array} obstructions - Array of obstruction points
     * @param {number} obstructions[].azimuth - Azimuth in degrees
     * @param {number} obstructions[].elevation - Elevation in degrees
     */
    setObstructions(obstructions) {
        this.obstructions = obstructions || [];
        this.draw();
    }
    
    /**
     * Set both satellites and obstructions
     * @param {Array} satellites - Satellite data
     * @param {Array} obstructions - Obstruction data
     */
    setData(satellites, obstructions) {
        this.satellites = satellites || [];
        this.obstructions = obstructions || [];
        this._updateTrailHistory(this.satellites);
        this.draw();
    }

    /**
     * Persist short history buffers for satellite trail rendering.
     * @private
     * @param {Array} satellites
     */
    _updateTrailHistory(satellites) {
        const now = Date.now();
        const activeKeys = new Set();

        satellites.forEach((sat) => {
            const key = sat.id || sat.name;
            if (!key) return;
            activeKeys.add(key);
            const trail = this.trailHistory.get(key) || [];
            trail.push({ azimuth: sat.azimuth, elevation: sat.elevation, ts: now });
            const minTs = now - this.trailMaxAgeMs;
            while (trail.length > 0 && trail[0].ts < minTs) {
                trail.shift();
            }
            if (trail.length > this.maxTrailPoints) {
                trail.splice(0, trail.length - this.maxTrailPoints);
            }
            this.trailHistory.set(key, trail);
        });

        // Keep memory bounded by removing stale satellites.
        Array.from(this.trailHistory.keys()).forEach((key) => {
            if (!activeKeys.has(key)) this.trailHistory.delete(key);
        });
    }
    
    /**
     * Animate satellite positions (for time-based animation)
     * @param {Array} satelliteSequence - Array of satellite position arrays
     * @param {number} interval - Animation interval in ms
     */
    animate(satelliteSequence, interval = 1000) {
        if (this.isAnimating) {
            this.stopAnimation();
        }
        
        if (!Array.isArray(satelliteSequence) || satelliteSequence.length === 0) return;
        if (!Number.isFinite(interval) || interval < 16) interval = 1000;
        let frameIndex = 0;
        this.isAnimating = true;
        
        const animate = () => {
            if (!this.isAnimating) return;
            
            this.satellites = satelliteSequence[frameIndex] || [];
            this.draw();
            
            frameIndex = (frameIndex + 1) % satelliteSequence.length;
            
            this.animationId = setTimeout(animate, interval);
        };
        
        animate();
    }
    
    /**
     * Stop animation
     */
    stopAnimation() {
        this.isAnimating = false;
        if (this.animationId) {
            clearTimeout(this.animationId);
            this.animationId = null;
        }
    }

    /**
     * Start the radar sweep animation loop.
     */
    startSweep() {
        if (this.sweepAnimationId) return;
        this.sweepActive = true;

        const animate = (ts) => {
            if (!this.sweepActive) {
                this.sweepAnimationId = null;
                return;
            }

            if (!this._lastSweepTick) this._lastSweepTick = ts;
            const delta = ts - this._lastSweepTick;
            this._lastSweepTick = ts;
            this.sweepAngle = (this.sweepAngle + (delta * 0.045 * this.fxProfile.speedMultiplier)) % 360;
            this.draw();
            this.sweepAnimationId = requestAnimationFrame(animate);
        };

        this.sweepAnimationId = requestAnimationFrame(animate);
    }

    /**
     * Stop radar sweep animation.
     */
    stopSweep() {
        this.sweepActive = false;
        this._lastSweepTick = 0;
        if (this.sweepAnimationId) {
            cancelAnimationFrame(this.sweepAnimationId);
            this.sweepAnimationId = null;
        }
    }
    
    /**
     * Handle canvas click/tap
     * @param {number} x - Click X coordinate
     * @param {number} y - Click Y coordinate
     * @returns {Object|null} Clicked satellite or polar coordinates
     */
    handleClick(x, y) {
        // Adjust for canvas scaling
        const rect = this.canvas.getBoundingClientRect();
        const scaleX = this.canvas.width / rect.width;
        const scaleY = this.canvas.height / rect.height;
        
        const canvasX = (x - rect.left) * scaleX;
        const canvasY = (y - rect.top) * scaleY;
        
        // Check if clicked on a satellite
        for (const sat of this.satellites) {
            const pos = this.polarToCartesian(sat.azimuth, sat.elevation);
            const distance = Math.sqrt(
                Math.pow(canvasX - pos.x, 2) + 
                Math.pow(canvasY - pos.y, 2)
            );
            
            if (distance <= 15 * this.dpr) {
                return { type: 'satellite', data: sat };
            }
        }
        
        // Return polar coordinates
        const polar = this.cartesianToPolar(canvasX, canvasY);
        return { type: 'coordinates', data: polar };
    }
    
    /**
     * Resize the canvas
     * @param {number} width - New width
     * @param {number} height - New height
     */
    resize(width, height) {
        this.width = width * this.dpr;
        this.height = height * this.dpr;
        
        this.canvas.width = this.width;
        this.canvas.height = this.height;
        this.canvas.style.width = `${width}px`;
        this.canvas.style.height = `${height}px`;
        
        this.radius = Math.min(this.width, this.height) / 2 - this.padding;
        this.centerX = this.width / 2;
        this.centerY = this.height / 2;
        
        this.draw();
    }
    
    /**
     * Export the sky plot as an image
     * @param {string} type - Image MIME type
     * @param {number} quality - Image quality (0-1)
     * @returns {string} Data URL
     */
    toDataURL(type = 'image/png', quality = 0.9) {
        return this.canvas.toDataURL(type, quality);
    }
    
    /**
     * Destroy the sky plot and clean up
     */
    destroy() {
        this.stopAnimation();
        this.stopSweep();
        document.removeEventListener('visibilitychange', this._visibilityHandler);
        this.satellites = [];
        this.obstructions = [];
        this.trailHistory.clear();
        this.clear();
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { SkyPlot };
}
