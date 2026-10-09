FROM node:22-alpine AS build
WORKDIR /web
COPY apps/web ./
RUN node scripts/build.js
FROM nginx:1.28-alpine
COPY --from=build /web/dist /usr/share/nginx/html
# Rendered at start with PUBLIC_ORIGIN / OIDC_PUBLIC_URL (local by default, private HTTPS address when remote access is on).
COPY deploy/local/nginx.conf.template /etc/nginx/templates/default.conf.template
ENV PUBLIC_ORIGIN=http://localhost OIDC_PUBLIC_URL=http://localhost:8081
