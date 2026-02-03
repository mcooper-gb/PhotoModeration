# Photo Moderation Service

Automated photo scanning service that detects explicit content, censors flagged images, and sends email notifications.

## How It Works

1. **Continuous Monitoring** - The service runs in a loop, scanning the designated directory for new images every 60 seconds
2. **Explicit Content Detection** - Uses NudeNet AI model to analyze images and detect explicit/NSFW content
3. **Smart Censoring** - When explicit content is detected, the service draws black boxes over flagged regions
4. **Email Notifications** - Sends email alerts with censored images attached when explicit content is found
5. **Duplicate Prevention** - Maintains a SQLite database to track processed files and avoid re-scanning
6. **Automatic Cleanup** - Removes censored images after successful email delivery to save disk space

## Installation

### Using Docker Compose (Recommended)

1. **Clone or copy the project files to your machine**

2. **Create a `.env` file** in the project directory:
```
EMAIL_ADDRESS=recipient@example.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASS=your-app-password
BATCH_SIZE=10
BATCH_TIMEOUT=60
CONFIDENCE_THRESHOLD=0.6
```

3. **Start the service:**
```bash
docker-compose up -d
```

### Using Published Docker Image

If using the pre-built image from Docker Hub, use this `docker-compose.yml`:

```yaml
version: '3.8'

services:
  photo-moderation:
    image: mcoopergb/photo-moderation:latest
    container_name: photo-moderation
    volumes:
      - ./images:/data/scan
      - photo-moderation-db:/data/db
      - ./censored:/data/censored
      - nudenet-models:/root/.NudeNet

    environment:
      - EMAIL_ADDRESS=${EMAIL_ADDRESS:-your-email@example.com}
      - SMTP_SERVER=${SMTP_SERVER:-smtp.gmail.com}
      - SMTP_PORT=${SMTP_PORT:-587}
      - SMTP_USER=${SMTP_USER:-your-smtp-user@gmail.com}
      - SMTP_PASS=${SMTP_PASS:-your-smtp-password}
      - BATCH_SIZE=${BATCH_SIZE:-10}
      - BATCH_TIMEOUT=${BATCH_TIMEOUT:-60}
      - CONFIDENCE_THRESHOLD=${CONFIDENCE_THRESHOLD:-0.6}
      - SCAN_DIR=/data/scan
      - CENSORED_DIR=/data/censored
      - DB_PATH=/data/db/scanned.db

    restart: unless-stopped

    healthcheck:
      test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  photo-moderation-db:
  nudenet-models:
```

## Usage

1. **Place images** in the `./images` directory
2. The service will automatically:
   - Scan for explicit content
   - Censor flagged images with black boxes
   - Send email notifications with censored images attached
   - Track processed files to avoid re-scanning

## Configuration

All settings can be configured via environment variables in the `.env` file:

- `EMAIL_ADDRESS` - Recipient email for notifications
- `SMTP_SERVER` - SMTP server address (default: smtp.gmail.com)
- `SMTP_PORT` - SMTP port (default: 587)
- `SMTP_USER` - SMTP username
- `SMTP_PASS` - SMTP password (use app-specific password for Gmail)
- `BATCH_SIZE` - Number of images to process per batch (default: 10)
- `BATCH_TIMEOUT` - Seconds to wait before sending incomplete batch when watching for new files (default: 60, set to 0 to disable)
  - During initial scan: batching always waits until batch is full or scan completes
  - During watch mode: sends notification after timeout even if batch is not full
- `CONFIDENCE_THRESHOLD` - Detection confidence threshold from 0.0 to 1.0 (default: 0.6)
  - Lower values (e.g., 0.4) = more sensitive, may have false positives
  - Higher values (e.g., 0.8) = less sensitive, only very confident detections

## Managing the Service

```bash
# Start service
docker-compose up -d

# Stop service
docker-compose down

# View logs
docker-compose logs -f

# Restart service
docker-compose restart
```
