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

ENV NODE_ENV=production
EXPOSE 3000

CMD ["node", "build"]
