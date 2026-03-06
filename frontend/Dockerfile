# LinkSpot Frontend Dockerfile
# React shell served at / with the legacy mission console mounted at /legacy/

FROM node:22-alpine AS app-build

WORKDIR /build/frontend-app

COPY app/package.json app/package-lock.json ./
RUN npm ci

COPY app/ ./
RUN npm run build

FROM nginx:1.25-alpine

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=app-build /build/frontend-app/dist/ /usr/share/nginx/html/
COPY index.html /usr/share/nginx/html/legacy/index.html
COPY manifest.json /usr/share/nginx/html/legacy/manifest.json
COPY sw.js /usr/share/nginx/html/legacy/sw.js
COPY css/ /usr/share/nginx/html/legacy/css/
COPY js/ /usr/share/nginx/html/legacy/js/

RUN echo '{"status":"healthy","service":"linkspot-frontend"}' > /usr/share/nginx/html/health \
    && chown -R nginx:nginx /usr/share/nginx/html \
    && chmod -R 755 /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1
