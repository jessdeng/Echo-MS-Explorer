###############################################################################
# Hugging Face Spaces / general container deploy
#
# Builds the echo-ms-explorer Shiny app into a slim image that listens on
# the port HF expects (7860). For local dev keep using the .command /
# .bat launchers — this Dockerfile is only for the cloud demo.
###############################################################################
FROM python:3.12-slim

# System deps. lxml (used by pyteomics) needs libxml2/libxslt at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (matches the local dev toolchain)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Hugging Face Spaces runs the container as user 1000.
RUN useradd -m -u 1000 app
USER app
ENV HOME=/home/app \
    PATH=/home/app/.local/bin:$PATH \
    UV_CACHE_DIR=/home/app/.cache/uv \
    PYTHONUNBUFFERED=1

WORKDIR /home/app/echo-ms-explorer

# Install Python deps from the locked manifest first so this layer caches
COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# App source
COPY --chown=app:app app/ ./app/
COPY --chown=app:app src/ ./src/

# Hugging Face Spaces expects the app on port 7860
EXPOSE 7860

CMD ["uv", "run", "shiny", "run", "app/app.py", \
     "--host", "0.0.0.0", "--port", "7860"]
