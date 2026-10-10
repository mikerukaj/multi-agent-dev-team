# Coder agent image. This container is the security boundary for generated code (spec FR-005a).
FROM python:3.12-slim

# tzdata: zoneinfo needs the IANA time zone database (e.g. America/Los_Angeles).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Chroma's default embedding model so the first run is not slow (research R5).
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction; \
DefaultEmbeddingFunction()(['warm up'])"

COPY . .

# Run as a non-root user so generated code cannot modify the image's system files.
RUN useradd --create-home agent && chown -R agent:agent /app
USER agent

# Default: the constitution's smoke test gate. Override to run a task, e.g.
#   docker compose run --rm agent python -m agents.coder_agent "Write hello world"
CMD ["pytest", "-m", "smoke", "-v"]
