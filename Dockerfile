# ── IncuBrix Long-Tail Distribution Service Dockerfile ──────
# Python 3.12 slim — minimal attack surface
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies (needed for asyncpg, Pillow, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (Docker cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full project
COPY . .

# Create output directories
RUN mkdir -p /app/outputs/mrss

# Expose the service port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start the FastAPI service
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
