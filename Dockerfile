FROM python:3.13-bookworm

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
RUN mkdir -p /data/scan /data/censored /data/db

# Set environment variables with defaults pointing to volume paths
ENV SCAN_DIR=/data/scan
ENV CENSORED_DIR=/data/censored
ENV DB_PATH=/data/db/scanned.db
ENV BATCH_SIZE=10

# Set Python path to include src directory
ENV PYTHONPATH=/app

# Run the application
CMD ["python", "app.py"]
