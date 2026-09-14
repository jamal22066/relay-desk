# ---- frontend build ----
FROM docker.io/library/node:22-alpine AS web

WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build

# ---- runtime ----
FROM docker.io/library/python:3.12-slim

# psycopg needs libpq at runtime; build tools are not needed for the wheels we use
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl libmagic1 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10001 relay
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini .
COPY scripts/ ./scripts/
COPY entrypoint.sh /entrypoint.sh

# built SPA, served by FastAPI as static files
COPY --from=web /build/dist ./static

RUN mkdir -p /var/lib/relay/uploads && chown -R relay:relay /var/lib/relay

USER relay
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
