# Pin exact version tag (no :latest)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for OCR and PDF rendering
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 10002 indexeruser && \
    useradd -u 10002 -g indexeruser -s /bin/bash -m indexeruser

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy pipeline code
COPY pipeline/ pipeline/

# Set ownership
RUN chown -R indexeruser:indexeruser /app

USER indexeruser

# Exec form ENTRYPOINT
ENTRYPOINT ["python", "-m", "pipeline.run"]

