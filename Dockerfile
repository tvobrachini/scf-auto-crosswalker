# ─── Builder stage: install the locked dependencies with uv ──────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Pinned uv, same version as CI.
RUN pip install --no-cache-dir uv==0.11.6

# Copy the lockfiles first so the dependency layer is cached.
COPY pyproject.toml uv.lock ./

# Every locked dependency ships a manylinux wheel for cp312, so no C toolchain
# is needed.
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# ─── Runtime stage: slim image, non-root user ────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/app \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY --from=builder /app /app

# data/ holds the downloaded SCF workbook, the parsed database and the
# embedding cache; ~/.cache holds the sentence-transformers model.
RUN mkdir -p /app/data /app/.cache && chown -R app:app /app/data /app/.cache

USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
