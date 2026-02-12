FROM python:3.11-slim AS base

LABEL maintainer="options-flow-scanner"
LABEL description="Real-time options flow scanner with Polygon.io"

# Prevent Python from writing .pyc and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY scanner/ scanner/
COPY main.py config.yaml ./

# Create data directory for CSV/SQLite output
RUN mkdir -p /app/data

# Non-root user for security
RUN adduser --disabled-password --gecos "" scanner && \
    chown -R scanner:scanner /app
USER scanner

# Health check (requires health endpoint — see scanner/health.py)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

EXPOSE 8080

ENTRYPOINT ["python", "main.py"]
