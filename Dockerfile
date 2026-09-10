# Chromium is not optional here. Ten of the twenty-two scrapers call fetch_page_js,
# because their vendors either render versions client-side or reject non-browser
# clients outright, so an image without a browser loses nearly half the catalogue.
# That is most of this image's size, and it buys working scrapers.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

WORKDIR /app

# Dependencies are installed from pyproject alone first, so editing application code
# does not invalidate the layer holding Chromium.
COPY pyproject.toml README.md ./
RUN mkdir -p src && touch src/__init__.py \
    && pip install --no-cache-dir -e ".[browser]" \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY templates ./templates
COPY static ./static
COPY scripts ./scripts
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# The database and the response cache both live on mounted volumes. They are created
# here so their ownership is right before the volume is attached, otherwise a
# non-root process cannot write to a fresh volume.
RUN useradd --create-home --uid 10001 tracker \
    && mkdir -p /data /app/.scrape_cache \
    && chown -R tracker:tracker /app /data /opt/playwright
USER tracker

ENV DATABASE_URL=sqlite+aiosqlite:////data/firmware_tracker.db

EXPOSE 8000

# Liveness only. /health/ready touches the database, which is the right check for a
# load balancer but wrong for a restart policy: a transient database problem should
# not put the container into a restart loop that cannot fix it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
