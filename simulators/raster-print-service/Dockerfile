FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data
COPY --chown=appuser:appuser app.py .

ENV RASTER_TEST_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8080
USER 10001:10001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
