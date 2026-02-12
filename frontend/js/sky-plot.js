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
            satellite: options.satelliteColor || '#e94560',
            obstructed: options.obstructedColor || '#6c757d',
            obstructionFill: options.obstructionFill || 'rgba(108, 117, 125, 0.3)',
            obstructionStroke: options.obstructionStroke || '#495057',
            grid: options.gridColor || 'rgba(255, 255, 255, 0.2)',
            text: options.textColor || '#a0a0a0',
            horizon: options.horizonColor || 'rgba(46, 139, 87, 0.5)',
            cardinal: options.cardinalColor || '#eaeaea'
        };
        
        // Data storage
        this.satellites = [];
        this.obstructions = [];
        this.horizonElevation = 10; // Minimum elevation for visibility
        
        // Animation
        this.animationId = null;
        this.isAnimating = false;
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
        ctx.setLineDash([]);
        
        // Draw elevation circles (30°, 60°)
        [30, 60].forEach(elevation => {
            const radius = (90 - elevation) / 90 * this.radius;
            ctx.beginPath();
            ctx.arc(this.centerX, this.centerY, radius, 0, Math.PI * 2);
            ctx.stroke();
            
            // Label
            ctx.fillStyle = this.colors.text;
            ctx.font = `${10 * this.dpr}px sans-serif`;
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
            ctx.font = `bold ${12 * this.dpr}px sans-serif`;
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
     * Draw obstruction profile
     * @private
     */
    drawObstructions() {
        if (!this.obstructions || this.obstructions.length === 0) return;
        
        const ctx = this.ctx;
        
        // Sort obstructions by azimuth
        const sorted = [...this.obstructions].sort((a, b) => a.azimuth - b.azimuth);
        
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
     * Draw satellites
     * @private
     */
    drawSatellites() {
        if (!this.satellites || this.satellites.length === 0) return;
        
        const ctx = this.ctx;
        
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
                ctx.beginPath();
                ctx.arc(pos.x, pos.y, 10 * this.dpr, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(233, 69, 96, 0.3)';
                ctx.fill();
            }
            
            // Draw satellite ID label
            ctx.fillStyle = this.colors.text;
            ctx.font = `${9 * this.dpr}px sans-serif`;
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
     * Draw the complete sky plot
     */
    draw() {
        this.clear();
        this.drawGrid();
        this.drawObstructions();
        this.drawSatellites();
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
        this.draw();
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
        this.satellites = [];
        this.obstructions = [];
        this.clear();
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { SkyPlot };
}
