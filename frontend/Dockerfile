# LinkSpot Frontend Dockerfile
# Nginx-based static file server for Leaflet/Canvas application

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
COPY css/ /usr/share/nginx/html/css/ 2>/dev/null || true
COPY js/ /usr/share/nginx/html/js/ 2>/dev/null || true
COPY assets/ /usr/share/nginx/html/assets/ 2>/dev/null || true
COPY images/ /usr/share/nginx/html/images/ 2>/dev/null || true

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
