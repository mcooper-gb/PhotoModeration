FROM python:3.13-slim-trixie

# Image metadata (appears in TrueNAS and other container managers)
LABEL org.opencontainers.image.source="https://github.com/mcooper-gb/PhotoModeration"
LABEL org.opencontainers.image.documentation="https://github.com/mcooper-gb/PhotoModeration"
LABEL org.opencontainers.image.url="https://hub.docker.com/r/mcoopergb/photo-moderation"
LABEL org.opencontainers.image.version="1.2.1"
LABEL org.opencontainers.image.title="Photo Moderation"
LABEL org.opencontainers.image.description="Automated media content moderation service using NudeNet, with Immich integration and a moderator dashboard"
LABEL org.opencontainers.image.vendor="Mark Cooper"
LABEL org.opencontainers.image.licenses="MIT"

# opencv-python-headless and onnxruntime bundle every native library they need
# (FFmpeg, OpenBLAS, libpng, zlib) inside their wheels, so the C++ runtime is
# the only system library either one links beyond glibc. The GL and X11 packages
# an earlier version installed were needed solely by the GUI build of OpenCV,
# which this image no longer contains.
#
# The upgrade picks up security updates published since the base image was
# built; without it the image ships whatever the base tag was baked with.
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get upgrade -y && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libstdc++6 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# The service decodes untrusted media with native code, so it drops root. The
# fixed uid matters: it is the owner Docker stamps onto a new volume mounted at
# any of these paths, and the uid an existing volume or bind mount has to allow.
RUN groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin app && \
    mkdir -p /data/scan /data/censored /data/db /data/review && \
    chown -R app:app /data

USER app

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
