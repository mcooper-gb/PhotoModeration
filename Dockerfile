FROM python:3.13-bookworm

# Image metadata (appears in TrueNAS and other container managers)
LABEL org.opencontainers.image.source="https://github.com/mcooper-gb/PhotoModeration"
LABEL org.opencontainers.image.documentation="https://github.com/mcooper-gb/PhotoModeration"
LABEL org.opencontainers.image.url="https://hub.docker.com/r/mcoopergb/photo-moderation"
LABEL org.opencontainers.image.version="1.2.0"
LABEL org.opencontainers.image.title="Photo Moderation"
LABEL org.opencontainers.image.description="Automated media content moderation service using NudeNet, with Immich integration and a moderator dashboard"
LABEL org.opencontainers.image.vendor="Mark Cooper"
LABEL org.opencontainers.image.licenses="MIT"

# Install system dependencies for OpenCV
RUN apt-get clean && \
    apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1-mesa-glx && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories that will be mounted as volumes
RUN mkdir -p /data/scan /data/censored /data/db /data/review

# Set environment variables with defaults pointing to volume paths
ENV SCAN_DIR=/data/scan
ENV CENSORED_DIR=/data/censored
ENV DB_PATH=/data/db/scanned.db
ENV REVIEW_DIR=/data/review
ENV REVIEW_DB_PATH=/data/db/review.db
ENV BATCH_SIZE=10
ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8080

# Set Python path to include src directory
ENV PYTHONPATH=/app

# Moderation dashboard
EXPOSE 8080

# Run the application
CMD ["python", "app.py"]
