# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# system deps (certs, curl helpful for debug)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies using uv
RUN uv sync --frozen

COPY . /app

# Expose port for Render (Render sets $PORT at runtime)
ENV PORT=8000
CMD ["uv", "run", "main.py"]