ARG DISTRO=bookworm
ARG PYTHON=3.13

FROM python:${PYTHON}-slim-${DISTRO} AS python

# --- Build Stage ---
FROM rust:slim-${DISTRO} AS builder
WORKDIR /app

# Install Build Dependencies
RUN --mount=target=/var/lib/apt/lists,type=cache,sharing=private \
    --mount=target=/var/cache/apt,type=cache,sharing=private \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential libssl-dev libffi-dev pkg-config

# Copy Python From Python Stage
COPY --from=python /usr/local /usr/local

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/pip,sharing=private \
    --mount=type=cache,target=/root/.cache/uv,sharing=private \
    --mount=type=cache,target=/usr/local/cargo/registry,sharing=private \
    pip3 install uv && \
    uv sync --frozen --no-dev --no-install-project --compile-bytecode

COPY . .
RUN python3 -m compileall -q /app/backend /app/frontend /app/Kapowarr.py

# --- Runtime Stage ---
FROM python:${PYTHON}-slim-${DISTRO} AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PUID=0 \
    PGID=0 \
    TZ=UTC

# Install Runtime Dependencies
RUN --mount=target=/var/lib/apt/lists,type=cache,sharing=private \
    --mount=target=/var/cache/apt,type=cache,sharing=private \
    apt-get update && \
    apt-get full-upgrade -y && \
    apt-get autoremove -y
COPY --from=tianon/gosu /gosu /usr/local/bin/

RUN groupadd -g 1000 kapowarr && \
    useradd -u 1000 -g kapowarr -d /nonexistent -M -s /bin/bash kapowarr && \
    mkdir -p /app/db /app/logs /app/temp_downloads

COPY --from=builder /app /app

EXPOSE 5656

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "/app/Kapowarr.py", "--LogFolder", "/app/logs"]