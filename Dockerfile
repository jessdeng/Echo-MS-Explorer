###############################################################################
# Hugging Face Spaces / general container deploy
#
# Builds the echo-ms-explorer Shiny app into a slim image that listens on
# the port HF expects (7860). For local dev keep using the .command /
# .bat launchers — this Dockerfile is only for the cloud demo.
###############################################################################
FROM python:3.12-slim

# System deps.
#   - libxml2 / libxslt1.1: runtime deps for lxml (used by pyteomics)
#   - build-essential + python3-dev: needed because pynumpress and a few
#     other deps ship sdists that have to compile against the Python
#     headers on python:3.12-slim (no manylinux wheel for cp312 yet)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
        ca-certificates \
        build-essential \
        python3-dev \
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

# Install Python deps from the locked manifest. We need to copy a few
# things *before* `uv sync` so hatchling can build the editable install
# of echo-ms-explorer:
#   - pyproject.toml + uv.lock: dep graph + lockfile
#   - README.md:                referenced from pyproject.toml's `readme`
#   - src/:                     the actual package being installed
COPY --chown=app:app pyproject.toml uv.lock README.md ./
COPY --chown=app:app src/ ./src/
RUN uv sync --frozen --no-dev

# App source (separate layer so dep installs are cached across app edits)
COPY --chown=app:app app/ ./app/

# Hugging Face Spaces expects the app on port 7860
EXPOSE 7860

CMD ["uv", "run", "shiny", "run", "app/app.py", \
     "--host", "0.0.0.0", "--port", "7860"]
