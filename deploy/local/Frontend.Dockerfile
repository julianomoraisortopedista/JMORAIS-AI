FROM node:22-alpine AS build
WORKDIR /web
COPY apps/web ./
RUN node scripts/build.js
RUN node -e "require('fs').writeFileSync('dist/workspace-config.json', JSON.stringify({environment:'DEVELOPMENT',issuer:'http://localhost:8081/realms/jmorais-local',client_id:'jmorais-local',redirect_uri:'http://localhost/',scopes:['openid','profile']}))"
FROM nginx:1.28-alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY deploy/local/nginx.conf /etc/nginx/conf.d/default.conf
