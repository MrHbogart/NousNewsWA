ARG NODE_BASE_IMAGE=node:20-alpine

FROM ${NODE_BASE_IMAGE} AS builder

WORKDIR /app

ENV NODE_ENV=development
ENV NPM_CONFIG_PRODUCTION=false
ENV NODE_OPTIONS=--max_old_space_size=4096
ENV NITRO_PORT=3001
ENV NITRO_HOST=0.0.0.0
ENV NUXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci --include=dev --no-audit --no-fund

COPY . .
RUN npm run build

# ---------- DEVELOPMENT ----------
# Used by docker-compose.dev.yml (build.target: development) for hot reload.
# The dev overlay bind-mounts ./frontend over /app and keeps this stage's
# node_modules via an anonymous volume, so `npm install` here is what
# actually provides dependencies inside the running container.

FROM ${NODE_BASE_IMAGE} AS development

WORKDIR /app

ENV NODE_ENV=development
ENV NITRO_HOST=0.0.0.0
ENV NITRO_PORT=3001
ENV NUXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci --include=dev --no-audit --no-fund

COPY . .

EXPOSE 3001

CMD ["npm", "run", "dev"]

# ---------- RUNNER ----------

FROM ${NODE_BASE_IMAGE} AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=3001
ENV NITRO_HOST=0.0.0.0
ENV NITRO_PORT=3001
ENV NUXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/.output ./.output
COPY --from=builder /app/public ./public

EXPOSE 3001

RUN apk add --no-cache curl ca-certificates && \
    chown -R node:node /app || true

USER node

CMD ["node", ".output/server/index.mjs"]
