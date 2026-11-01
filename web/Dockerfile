# syntax=docker/dockerfile:1.7
#
# R7: the web front end's image (docker-compose.yml's web service builds it on the NAS, from web/). A build of web/
# as CI checks one (npm ci from the lockfile, npm run build), served by nginx with no access log. Both bases are pinned
# by digest, as cloudflared's is: a tag moves under a 24/7 box. The tag beside each digest says which version it is.
# 中文：新前端的镜像（compose 的 web 服务在 NAS 上从 web/ 构建）。照 CI 的做法构建 web/，由不记访问日志的 nginx
# 提供。两个基础镜像都钉 digest，和 cloudflared 一样：标签会动。

FROM node:24.22.2-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# The API a page calls and the site its shared links name: compose passes both, and src/api/apiBase.ts refuses a build
# for anything but an https origin. Declared after npm ci, so a new value reuses the installed packages.
ARG VITE_API_BASE_URL
ARG VITE_PUBLIC_BASE_URL
RUN test -n "$VITE_API_BASE_URL" && test -n "$VITE_PUBLIC_BASE_URL" \
    && npm run build \
    && node deploy/render-headers.ts dist/.vite/security-headers.json > security-headers.conf \
    && rm -r dist/.vite

# Runs as nginx's user 101 and listens on 8080; compose adds a read-only root with /tmp in memory.
FROM nginxinc/nginx-unprivileged:1.30.6-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /web/dist/ /srv/www/
