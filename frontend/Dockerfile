FROM node:26-alpine AS builder
RUN apk upgrade --no-cache

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG GIT_SHA=""
ARG APP_VERSION=""
RUN GIT_SHA="$GIT_SHA" APP_VERSION="$APP_VERSION" npm run build

FROM node:26-alpine AS runner
RUN apk upgrade --no-cache

# Run as the built-in unprivileged 'node' user (UID 1000).
RUN mkdir -p /app && chown node:node /app
WORKDIR /app
USER node

COPY --from=builder --chown=node:node /app/build ./build
COPY --from=builder --chown=node:node /app/package*.json ./
RUN npm ci --omit=dev

# npm is only needed for the install above — the container runs `node build` at
# runtime, never npm. Remove the image-bundled npm CLI so its vendored deps
# (tar, brace-expansion, …) don't ship in the scanned runtime image. This ends
# the recurring "npm-bundled CVE" failures: the node:26-alpine npm pins those
# transitively and npm@latest (12.0.1) still vendors the vulnerable
# brace-expansion 5.0.7 (CVE-2026-14257), so there is no npm version to bump to.
USER root
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx
USER node

ENV NODE_ENV=production
EXPOSE 3000

CMD ["node", "build"]
