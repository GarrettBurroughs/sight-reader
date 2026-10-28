# syntax=docker/dockerfile:1.7
# The whole app in one image: built web pages, the API, the excerpt library, and Litestream.
# CI unpacks the library version named in library.version into build/library before building.

FROM node:22.23.2-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12.14-slim-bookworm
ARG LITESTREAM_VERSION=0.5.17
ARG LITESTREAM_SHA256=cfb371176d164437ae869f8351cfde49bd1804ae71c61923f75c9cba9c9c006d
ADD --checksum=sha256:${LITESTREAM_SHA256} \
    https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-x86_64.tar.gz \
    /tmp/litestream.tar.gz
RUN tar -xzf /tmp/litestream.tar.gz -C /usr/local/bin litestream && rm /tmp/litestream.tar.gz

WORKDIR /app
COPY server/requirements.txt server/
RUN pip install --no-cache-dir -r server/requirements.txt
COPY build/library/ library/
COPY pipeline/*.py pipeline/
COPY server/*.py server/
COPY --from=web /web/dist/ web/

ARG VERSION=dev
ENV SIGHTREADER_DB=/data/app.sqlite \
    SIGHTREADER_LIBRARY=/app/library \
    SIGHTREADER_STATIC=/app/web \
    SIGHTREADER_SECURE_COOKIE=1 \
    SIGHTREADER_VERSION=${VERSION} \
    PYTHONUNBUFFERED=1
# Cloud Run sends SIGTERM before stopping an instance; uvicorn then runs the shutdown hook,
# which lets Litestream do its final sync and releases the database lock.
CMD exec uvicorn app:create_app --factory --app-dir server --host 0.0.0.0 --port ${PORT:-8080} \
    --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 8
