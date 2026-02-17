FROM node:20-alpine AS builder

WORKDIR /app

ENV NODE_ENV=development
ENV NPM_CONFIG_PRODUCTION=false
ENV NODE_OPTIONS=--max_old_space_size=4096
ENV NITRO_PORT=3001
ENV NITRO_HOST=0.0.0.0
ENV NUXT_TELEMETRY_DISABLED=1

COPY package.json .

RUN npm install --include=dev --no-audit --no-fund

COPY . .

RUN npm run build

FROM node:20-alpine AS runner

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

RUN apk add --no-cache curl ca-certificates

RUN chown -R node:node /app || true

USER node

CMD ["node", ".output/server/index.mjs"]
