FROM python:3.13-slim@sha256:eb43ff125d8d58d7449dcba7d336c23bcac412f526d861db493b9994d8010280

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for running the application
RUN groupadd -r aexy && useradd -r -g aexy aexy

# Copy all application files first
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Set ownership of the app directory
RUN chown -R aexy:aexy /app

# Set Python path
ENV PYTHONPATH=/app/src

# Switch to non-root user
USER aexy

# Default command (can be overridden)
CMD ["uvicorn", "aexy.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
