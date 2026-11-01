# R7: the web front end's image (docker-compose.yml's web service builds it on the NAS, from web/). A build of web/
# as CI checks one (npm ci from the lockfile, npm run build), served by nginx with no access log. Both bases are pinned
# by digest, as cloudflared's is: a tag moves under a 24/7 box. The tag beside each digest says which version it is.
# No `# syntax=` line: the builder's own Dockerfile frontend reads this file, rather than one fetched by its tag.
# 中文：新前端的镜像（compose 的 web 服务在 NAS 上从 web/ 构建）。照 CI 的做法构建 web/，由不记访问日志的 nginx
# 提供。两个基础镜像都钉 digest，和 cloudflared 一样：标签会动。不写 `# syntax=`：用构建器自带的前端，不按标签另取。

FROM node:24.22.2-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS build
WORKDIR /web
# The digest decides which image this is, not the tag beside it: stop unless it is Node 24, as CI builds with.
RUN node --version | grep -q '^v24\.' || { echo "Not Node 24: $(node --version)" >&2; exit 1; }
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# The API a page calls and the site its shared links name: compose passes both, and src/api/apiBase.ts refuses a build
# for anything but an https origin. A value that is blank, or only spaces, it reads as none given and falls back to
# production's API and compass, so the guard here wants each to begin with https:// itself. Declared after npm ci, so a
# new value reuses the installed packages.
ARG VITE_API_BASE_URL
ARG VITE_PUBLIC_BASE_URL
RUN for value in "$VITE_API_BASE_URL" "$VITE_PUBLIC_BASE_URL"; do \
      case "$value" in https://?*) ;; *) echo "Not an https origin: '$value'" >&2; exit 1 ;; esac; \
    done \
    && npm run build \
    && node deploy/render-headers.ts dist/.vite/security-headers.json > security-headers.conf \
    && rm -r dist/.vite

# Runs as nginx's user 101 and listens on 8080; compose adds a read-only root with /tmp in memory.
FROM nginxinc/nginx-unprivileged:1.30.6-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /web/dist/ /srv/www/
