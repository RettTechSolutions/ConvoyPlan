FROM node:26-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG GIT_SHA=""
RUN GIT_SHA="$GIT_SHA" npm run build

FROM node:26-alpine AS runner

WORKDIR /app
COPY --from=builder /app/build ./build
COPY --from=builder /app/package*.json ./
RUN npm ci --omit=dev

ENV NODE_ENV=production
EXPOSE 3000

CMD ["node", "build"]
