# syntax=docker/dockerfile:1.7
#
# AgentThreshold — production container image.
#
# A single parametrized Dockerfile builds every service:
#   docker buildx bake                          # all services
#   docker buildx bake api-gateway              # one service
#
# Build args:
#   PACKAGE     uv workspace package to install (e.g. at-api-gateway)
#   APP_MODULE  uvicorn import string for the app (e.g. app.main:app)
#
# Design notes:
#   * Multi-stage: a uv builder seals a standalone .venv (--no-editable), the
#     runtime stage is a bare python:slim with only that .venv — no sources,
#     no dev deps, no shell tooling beyond what the process needs.
#   * Non-root (uid/gid 10001), read-only-friendly /app.
#   * Every service exposes GET /healthz for the container HEALTHCHECK.
#   * Runtime port overridable via PORT (default 8000).

# ---------------------------------------------------------------------------
# Builder — resolve + install the service closure into /build/.venv
# ---------------------------------------------------------------------------
# The uv tool image ships a static musl binary; copy it onto the same python
# base as the runtime so the sealed .venv's interpreter symlinks resolve to a
# path that exists in the final image (relocatable venv).
FROM ghcr.io/astral-sh/uv:0.11.25-debian-slim AS uv-tool

FROM python:3.13-slim AS builder

COPY --from=uv-tool /usr/local/bin/uv /usr/local/bin/uv
RUN addgroup --system --gid 10001 app && \
    adduser --system --uid 10001 --gid 10001 --home /build app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=3.13 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/venv

WORKDIR /build

# Lockfile first, then the workspace member sources the package depends on.
# The uv cache mount keeps rebuilds fast when only source changes.
COPY pyproject.toml uv.lock ./
COPY shared ./shared
COPY sdk ./sdk
COPY services ./services

ARG PACKAGE
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --package "${PACKAGE}" --frozen --no-dev --no-editable

# ---------------------------------------------------------------------------
# Runtime — minimal python slim + sealed .venv + non-root user
# ---------------------------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH"

WORKDIR /app

# App user must be created BEFORE perl is purged (adduser/addgroup are perl
# scripts in Debian).
RUN addgroup --system --gid 10001 app && \
    adduser --system --uid 10001 --gid 10001 --home /app app

# Debian security updates (perl, util-linux, ...) on top of the pinned slim base.
# perl-base is "essential" in Debian but has no reverse-deps in this image and
# nothing at runtime needs it — purging removes 9 CVEs (4 CRITICAL) that have no
# fix released yet. gzip/acl/ncurses/openssl remain (OS-runtime essentials).
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
    && DEBIAN_FRONTEND=noninteractive apt-get purge -y --allow-remove-essential perl-base \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=app:app /venv /venv

# Remove pip and its vendored packages (msgpack, pkg_resources) — a production
# runtime has no business installing packages, and it removes a CVEs source.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip* \
    /usr/local/lib/python3.13/site-packages/README.txt

ARG APP_MODULE
ENV APP_MODULE=${APP_MODULE}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["/venv/bin/python", "-c", \
        "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+__import__('os').getenv('PORT','8000')+'/healthz', timeout=4).status==200 else 1)"]

USER app
ENTRYPOINT ["/bin/sh", "-c"]
CMD ["uvicorn $APP_MODULE --host 0.0.0.0 --port ${PORT:-8000}"]