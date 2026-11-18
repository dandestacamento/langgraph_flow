# Multi-stage build per instructions/learnings/chat-ui-plan1.md section
# 2.5/4 (Phase C). Stage 1 builds the static bundle with the full Node
# toolchain; stage 2 serves it with a minimal nginx image - the final
# image ships no Node, no source, no node_modules, just dist/ + nginx.

FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# Config lives in /etc/nginx/templates/ - the official nginx image's own
# entrypoint script (docker-entrypoint.d/20-envsubst-on-templates.sh)
# automatically runs envsubst over every *.template file in this
# directory at container startup, writing the result into
# /etc/nginx/conf.d/, so BACKEND_HOST/BACKEND_PORT below are resolved at
# `docker run` time, not baked in at build time - no custom entrypoint
# script needed. Defaults match this project's own local dev convention
# (FastAPI backend on port 8000); override with
# `docker run -e BACKEND_HOST=... -e BACKEND_PORT=...`.
ENV BACKEND_HOST=backend
ENV BACKEND_PORT=8000
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/ || exit 1
