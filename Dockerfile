# syntax=docker/dockerfile:1
FROM python:3.12-alpine@sha256:78098ea6a3a9c6a7727a5d4674e4a44e57e01fac878ee9cb4d24a86bd93916ff AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY requirements-build.lock ./
COPY jmoraIs ./jmoraIs
COPY evaluation ./evaluation
COPY services ./services
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-build.lock \
    && python -m build --no-isolation --wheel --outdir /dist

FROM python:3.12-alpine@sha256:78098ea6a3a9c6a7727a5d4674e4a44e57e01fac878ee9cb4d24a86bd93916ff AS runtime
ARG JMORAIS_VERSION
ARG JMORAIS_SOURCE_REVISION
ARG JMORAIS_BUILD_ID
ARG JMORAIS_BUILD_TIMESTAMP
LABEL org.opencontainers.image.title="JMORAIS-AI" \
      org.opencontainers.image.version=$JMORAIS_VERSION \
      org.opencontainers.image.revision=$JMORAIS_SOURCE_REVISION \
      org.opencontainers.image.created=$JMORAIS_BUILD_TIMESTAMP \
      ai.jmorais.build-id=$JMORAIS_BUILD_ID \
      ai.jmorais.supply-chain-policy="supply-chain-policy-v1"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/nonexistent TMPDIR=/tmp/jmorais PORT=8080
RUN addgroup -S -g 10001 jmorais && adduser -S -D -H -u 10001 -G jmorais -s /sbin/nologin jmorais \
    && mkdir -p /tmp/jmorais && chown 10001:10001 /tmp/jmorais
WORKDIR /app
COPY requirements-production.lock ./
COPY --from=builder /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-production.lock \
    && python -m pip install --no-cache-dir --no-deps /tmp/*.whl \
    && rm -f /tmp/*.whl requirements-production.lock
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/internal/api/v1/health/live', timeout=2)"]
CMD ["python", "-m", "uvicorn", "jmoraIs.api.production_asgi:create", "--factory", "--host", "127.0.0.1", "--port", "8080", "--workers", "2", "--limit-concurrency", "100", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "30", "--no-server-header"]
