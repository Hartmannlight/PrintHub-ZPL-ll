FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ZPLGRID_TEMPLATES_DIR=/data/templates \
    ZPLGRID_PRINT_DRAFTS_DIR=/data/drafts

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libdmtx0t64 libdmtx-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock README.md /app/
COPY zplgrid /app/zplgrid

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /data/templates /data/drafts \
    && chown -R appuser:appuser /data /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "zplgrid.api:app", "--host", "0.0.0.0", "--port", "8000"]
