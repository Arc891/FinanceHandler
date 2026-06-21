FROM python:3.12-slim

# This host has no working IPv6 route, but DNS still returns AAAA records, so
# anything that tries IPv6 first (pip, and at runtime Discord/Google) hits
# "Network is unreachable". no-aaaa makes glibc skip AAAA lookups -> IPv4 only.
# Applies to every build RUN below and to the running container.
ENV RES_OPTIONS=no-aaaa

# Update system packages to patch vulnerabilities and remove package cache
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies (IPv4 forced via RES_OPTIONS env above)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY src/ ./src/

# Create data directories
RUN mkdir -p data/sessions data/uploads

# Set Python path and ensure unbuffered output
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
  chown -R appuser:appuser /app
USER appuser

# Set HOME for Claude CLI to find config
ENV HOME=/home/appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import discord; print('OK')" || exit 1

# Run the bot with unbuffered output
CMD ["python", "src/bot.py"]
