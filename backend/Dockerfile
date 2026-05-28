# Use an official lightweight Python base image
FROM python:3.12-slim

# Install uv binary directly from the official image using multi-stage build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Optimize uv performance specifically for containerized environments
# 1. Compile Python source files to bytecode (.pyc) for faster container startup times
# 2. Use 'copy' link mode to prevent hard link constraints across virtual filesystems
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Set the runtime working directory inside the container
WORKDIR /app

# Copy dependency definition maps first to leverage Docker layer caching architecture
# (Note: This assumes the build context in docker-compose is mapped to './backend')
COPY pyproject.toml uv.lock ./

# Install production dependencies only (skip development-only packages)
# The --frozen flag ensures uv strictly mirrors the exact versions pinned in uv.lock
RUN uv sync --frozen --no-install-project --no-dev

# Copy the remaining backend application source code layers into the container
COPY . .

# Pre-append the uv virtual environment binary directory to system PATH
# This allows direct invocation of executable packages like 'uvicorn' without prefixing 'uv run'
ENV PATH="/app/.venv/bin:$PATH"

# Expose the application network port mapped to the FastAPI ASGI config
EXPOSE 8000

# Fire up the production ASGI server instance using Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]