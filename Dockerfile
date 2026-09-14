FROM python:3.14-slim-trixie

# Image metadata (appears in TrueNAS and other container managers)
LABEL org.opencontainers.image.source="https://github.com/mcooper-gb/PhotoModeration"
LABEL org.opencontainers.image.documentation="https://github.com/mcooper-gb/PhotoModeration"
LABEL org.opencontainers.image.url="https://hub.docker.com/r/mcoopergb/photo-moderation"
LABEL org.opencontainers.image.version="1.2.1"
LABEL org.opencontainers.image.title="Photo Moderation"
LABEL org.opencontainers.image.description="Automated media content moderation service using NudeNet, with Immich integration and a moderator dashboard"
LABEL org.opencontainers.image.vendor="Mark Cooper"
LABEL org.opencontainers.image.licenses="MIT"

# Apply the base image's outstanding security updates, then add libgomp.so.1 for
# onnxruntime. Headless OpenCV needs no X11 or GL libraries.
#
# SECURITY_REFRESH exists only to be part of this layer's cache key. The command text
# never changes, so without it Docker serves the layer from cache and the upgrade
# silently stops running until the base image digest moves - which lags Debian's own
# security uploads. Release builds pass a fresh value:
#   docker build --pull --build-arg SECURITY_REFRESH=$(Get-Date -Format yyyy-MM-dd) .
ARG SECURITY_REFRESH=2026-09-14
RUN echo "security refresh: ${SECURITY_REFRESH}" && \
    apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies, then strip the packaging toolchain the runtime never
# uses. pip is the one that matters: its vendored copies of msgpack and setuptools were
# the only remaining source of HIGH findings, and nothing on the inference path imports
# it. The setuptools and wheel uninstall is a guard rather than a fix - this base image
# ships neither, so it is a no-op today and only earns its keep if a future dependency
# drags them back in.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y setuptools wheel && \
    rm -rf /usr/local/lib/python3.*/site-packages/pip \
           /usr/local/lib/python3.*/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.*/ensurepip \
           /usr/local/bin/pip /usr/local/bin/pip3*

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

# Stream stdout and stderr straight to the container log. Python buffers when stdout is
# a pipe rather than a tty, so without this `docker logs` on a healthy container stays
# empty until the process exits - and this image deliberately keeps no pip or build
# tooling to debug with instead.
ENV PYTHONUNBUFFERED=1

# Moderation dashboard
EXPOSE 8080

# Run the application
CMD ["python", "app.py"]
