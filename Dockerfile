FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gcc \
        g++ \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./

RUN uv sync --frozen --no-dev \
    --extra api \
    --extra orchestrator \
    --extra agent \
    --extra ui \
    --extra browser \
    --extra openstat

RUN uv run playwright install --with-deps chromium
RUN uv run scrapling install

COPY . .

RUN groupadd -r appuser \
    && useradd -r -m -d /home/appuser -g appuser -u 1000 appuser \
    && mkdir -p /tmp/uv-cache /ms-playwright \
    && chown -R appuser:appuser /app /home/appuser /tmp/uv-cache /ms-playwright

USER appuser

EXPOSE 8000 8001

# Use venv binaries directly — avoid `uv run` (needs writable cache as appuser).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
