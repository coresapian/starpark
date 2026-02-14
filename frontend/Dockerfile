# LinkSpot Frontend Dockerfile
# Multi-stage build: Node.js for anymap-ts bundle, Nginx for serving

# Stage 1: Build anymap-ts bundle
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files and install dependencies
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install

# Copy source files for building
COPY src/ ./src/

# Build the anymap-ts bundle
RUN npm run build:prod

# Stage 2: Nginx-based static file server
FROM nginx:1.25-alpine

# Install envsubst for environment variable substitution
RUN apk add --no-cache gettext

# Remove default nginx configuration
RUN rm /etc/nginx/conf.d/default.conf

# Create directory for static files
RUN mkdir -p /usr/share/nginx/html \
    && chown -R nginx:nginx /usr/share/nginx/html

# Copy static files
COPY index.html /usr/share/nginx/html/
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/

# Copy built anymap-ts bundle from builder stage
COPY --from=builder /app/js/anymap-bundle.js /usr/share/nginx/html/js/anymap-bundle.js
COPY --from=builder /app/js/anymap-bundle.css /usr/share/nginx/html/js/anymap-bundle.css

# Copy custom nginx configuration template
COPY nginx.conf /etc/nginx/conf.d/default.conf.template

# Create health check endpoint
RUN echo '{"status":"healthy","service":"linkspot-frontend"}' > /usr/share/nginx/html/health

# Set proper permissions
RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chmod -R 755 /usr/share/nginx/html

# Expose port 80
EXPOSE 80

# Create entrypoint script for environment substitution
RUN echo '#!/bin/sh\n\
envsubst < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf\n\
exec nginx -g "daemon off;"' > /docker-entrypoint.sh \
    && chmod +x /docker-entrypoint.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

# Start nginx with environment substitution
ENTRYPOINT ["/docker-entrypoint.sh"]
