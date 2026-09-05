FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS dependencies
# renovate: datasource=pypi depName=poetry
ARG POETRY_VERSION=2.4.1
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir poetry==$POETRY_VERSION
ENV POETRY_VIRTUALENVS_IN_PROJECT=true POETRY_VIRTUALENVS_OPTIONS_NO_PIP=true POETRY_NO_INTERACTION=1
COPY pyproject.toml poetry.lock README.md ./
RUN poetry check --lock && poetry sync --only main --no-root

FROM base AS runtime
RUN python -m pip uninstall -y setuptools wheel pip
RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript libcups2 libdmtx0b poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data/templates /data/drafts /data/print-jobs /app/configs \
    && chown -R appuser:appuser /data /app/configs
COPY --from=dependencies /app/.venv /app/.venv
COPY zplgrid ./zplgrid
COPY templates /app/templates
ENV PATH=/app/.venv/bin:$PATH \
    ZPLGRID_TEMPLATES_DIR=/data/templates \
    ZPLGRID_BUNDLED_TEMPLATES_DIR=/app/templates \
    ZPLGRID_PRINT_DRAFTS_DIR=/data/drafts \
    ZPLGRID_PRINT_JOBS_DIR=/data/print-jobs \
    ZPLGRID_COUNTERS_PATH=/data/counters.json \
    ZPLGRID_PRINTER_REGISTRY_PATH=/data/printers.sqlite3
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
CMD ["python", "-m", "zplgrid.container_entrypoint"]
