FROM python:3.13-slim

ENV PYTHONUNBUFFERED 1

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.5.9 /uv /uvx /bin/

RUN apt-get update && apt-get install -y libsndfile1 libspeexdsp-dev git && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -s /sbin/nologin -M appuser

# Copy the application into the container.
COPY pyproject.toml README.md uv.lock /app
COPY src /app/src
RUN uv sync --frozen --no-cache

# Set the user to 'appuser'
USER appuser

ENV PRIVATE_ASSISTANT_CONFIG_PATH=template.yaml

CMD ["/app/.venv/bin/private-assistant-spotify-skill"]
