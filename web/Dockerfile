# syntax=docker/dockerfile:1.6

# -----------------------------------------------------------------------------
# Builder stage
# -----------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /build

# Install deps from lockfile so the image is reproducible.
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build the production bundle. Tailwind v4 plus the App
# Router emit a standalone server under .next/standalone when configured;
# otherwise we ship the full .next directory.
COPY . .
RUN npm run build

# -----------------------------------------------------------------------------
# Runtime stage
# -----------------------------------------------------------------------------
FROM node:20-alpine AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

WORKDIR /app

# Non-root user for the runtime container.
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /build/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /build/public ./public
COPY --from=builder --chown=nextjs:nodejs /build/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /build/package.json ./package.json

USER nextjs

EXPOSE 3000

# `next start` reads PORT from the env. It binds to 0.0.0.0 by default which
# is what we need inside a container.
CMD ["npm", "start"]
