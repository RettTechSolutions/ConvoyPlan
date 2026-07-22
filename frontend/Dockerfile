FROM node:26-alpine AS builder
RUN apk upgrade --no-cache
# Upgrade the image-bundled npm: the node:26-alpine default npm vendors
# tar 7.5.16 (CVE-2026-59873 CRITICAL / CVE-2026-59874 HIGH) and
# brace-expansion 5.0.6 (CVE-2026-13149 HIGH) in /usr/local/lib/node_modules/npm.
# npm 12.0.1 bundles the patched tar 7.5.19 and brace-expansion 5.0.7.
RUN npm install -g npm@12.0.1 && npm cache clean --force

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG GIT_SHA=""
ARG APP_VERSION=""
RUN GIT_SHA="$GIT_SHA" APP_VERSION="$APP_VERSION" npm run build

FROM node:26-alpine AS runner
RUN apk upgrade --no-cache
# Upgrade the image-bundled npm so the final runtime image is free of the
# vulnerable tar/brace-expansion versions vendored by the default npm
# (see builder stage). This is the image Trivy scans in CI.
RUN npm install -g npm@12.0.1 && npm cache clean --force

# Run as the built-in unprivileged 'node' user (UID 1000).
RUN mkdir -p /app && chown node:node /app
WORKDIR /app
USER node

COPY --from=builder --chown=node:node /app/build ./build
COPY --from=builder --chown=node:node /app/package*.json ./
RUN npm ci --omit=dev

ENV NODE_ENV=production
EXPOSE 3000

CMD ["node", "build"]
