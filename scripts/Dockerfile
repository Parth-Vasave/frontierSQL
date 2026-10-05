# One-off image for the data pipeline (download + clean + seed). Run via: docker compose run --rm seed
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /work

# psql: scripts/bird.py loads the BIRD benchmark dump with it.
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/requirements.txt scripts/requirements.txt
RUN pip install --no-cache-dir -r scripts/requirements.txt

COPY scripts ./scripts
CMD ["sh", "-c", "python -m scripts.ingest_data && python -m scripts.clean_data && python -m scripts.seed_database"]
