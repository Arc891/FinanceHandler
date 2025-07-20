FROM python:3.12-slim

# Update system packages to patch vulnerabilities and remove package cache
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies (most packages don't need compilation)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY src/ ./src/
COPY config/ ./config/

# Create data directories
RUN mkdir -p data/sessions data/uploads

# Set Python path
ENV PYTHONPATH="/app/src"

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
  chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import discord; print('OK')" || exit 1# Run the bot
CMD ["python", "src/bot.py"]
