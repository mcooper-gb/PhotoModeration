# Project Architecture

This document describes the refactored architecture of the Photo Moderation Service.

## Directory Structure

```
PhotoModeration/
├── app.py                      # Main entry point
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker configuration
├── docker-compose.yml          # Docker Compose configuration
├── .dockerignore               # Docker ignore patterns
├── README.md                   # User documentation
├── ARCHITECTURE.md             # This file
│
└── src/                        # Source code
    ├── __init__.py
    ├── config.py               # Configuration management
    │
    ├── services/               # Core business logic
    │   ├── __init__.py
    │   ├── scanner.py          # File scanning and tracking
    │   ├── moderator.py        # Content detection and redaction
    │   ├── immich.py           # Immich API client
    │   ├── review_store.py     # Moderation review queue
    │   ├── notifier.py         # Email notification service
    │   ├── batch_manager.py    # Notification batching
    │   └── watcher.py          # File system watching
    │
    ├── utils/                  # Utility modules
    │   ├── __init__.py         # Processing pipeline helpers
    │   ├── redaction.py        # Blur / pixelate / box redaction
    │   └── exif_extractor.py   # EXIF metadata extraction
    │
    ├── templates/              # Email templates
    │   ├── __init__.py
    │   ├── email_template.py   # Moderator alert email
    │   └── owner_notification_template.py  # Uploader notification email
    │
    └── web/                    # Moderation dashboard
        ├── __init__.py
        ├── dashboard.py        # Flask application and routes
        ├── templates/          # Jinja page templates
        └── static/             # Dashboard stylesheet
```

## Module Descriptions

### app.py
Main entry point for the application. Orchestrates the initialization of all services and manages the main execution flow.

### src/config.py
Manages application configuration from environment variables. Validates required settings on startup.

### src/services/

#### scanner.py
- Tracks processed files using SQLite database
- Identifies new files that need processing
- Prevents duplicate processing

#### moderator.py
- Detects explicit content using NudeNet
- Handles both images and videos
- Redacts detected regions by blurring them (pixelate and black box are also available)
- Rescales detection boxes back to full resolution when video frames were downscaled
- Optimizes video processing with frame sampling
- Re-extracts individual video frames on demand for the dashboard

#### immich.py
- Wraps the Immich REST API (base path `/api`, `x-api-key` auth)
- Matches a file on disk to an Immich asset by filename UUID, SHA1 checksum,
  original path, then original filename
- Resolves the uploader, falling back to the user id or storage label in the library path
- Deletes assets through the API so the Immich database is never left with orphaned rows
- Selects a per-user API key when one is configured, since Immich keys are user scoped

#### review_store.py
- SQLite queue of flagged detections backing the dashboard
- Retains a copy of the redacted preview that outlives the email batch
- Upserts on rescan so a modified file returns to the queue instead of duplicating
- Tracks status (pending, kept, deleted, error), the outcome detail and owner notification
- Purges resolved items past the retention window

#### notifier.py
- Sends HTML email notifications to the moderator
- Enriches detection data with EXIF metadata
- Embeds redacted previews inline in emails
- Notifies the asset owner when a moderator deletes their upload
- Handles SMTP communication

#### watcher.py
- Monitors directory for new files
- Triggers processing pipeline for new media
- Batches notifications for efficiency
- Manages cleanup of temporary censored files

### src/utils/

#### __init__.py
- Drives the per-file pipeline: detect, redact, resolve the Immich asset, queue for review
- Builds notification batch items and dashboard review links

#### redaction.py
- Selects the boxes to obscure from detections above the confidence threshold
- Applies a Gaussian blur, a mosaic, or a solid box scaled to the region size

#### exif_extractor.py
- Extracts EXIF metadata from images
- Parses GPS coordinates
- Converts GPS data to decimal format
- Generates Google Maps links

### src/templates/

#### email_template.py
- Generates the moderator alert email
- Shows the uploader, review link and Immich link for each detection
- Escapes values that come from file metadata
- Handles inline image embedding

#### owner_notification_template.py
- Generates the plain text and HTML email sent to an uploader whose asset was removed

### src/web/

#### dashboard.py
- Flask application serving the moderation queue
- Serves redacted previews by default; originals only when explicitly revealed
- Applies moderation decisions: keep, delete (trash or permanent), restore
- Optionally emails the uploader as part of a deletion
- Optional HTTP basic auth, served by waitress when available

## Data Flow

1. **Initial Scan** (startup):
   - Scanner identifies unprocessed files
   - Moderator detects and blurs explicit content
   - Immich client resolves the asset and its uploader
   - Detection is queued in the review store for the dashboard
   - Notifier sends batch email notifications
   - Redacted previews in the email batch are cleaned up (the review copy is retained)

2. **File Watching** (ongoing):
   - Watcher monitors directory for new files
   - New files trigger the moderation pipeline
   - Results are batched and sent via email
   - Database tracks processed files

3. **Email Generation**:
   - Notifier enriches results with EXIF data
   - EmailTemplate generates styled HTML with uploader, review and Immich links
   - Images embedded inline with Content-ID
   - Email sent via SMTP

4. **Moderation** (dashboard):
   - Moderator works through the pending queue, seeing redacted previews
   - Revealing the original reads from the source file, or re-extracts a video frame
   - Deleting calls the Immich API (trash by default) and optionally emails the uploader
   - Outcome and notification state are recorded against the review item

## Design Principles

### Separation of Concerns
Each module has a single, well-defined responsibility:
- Services handle business logic
- Utils provide reusable functionality
- Templates manage presentation

### Maintainability
- Clear module boundaries
- Self-documenting code with docstrings
- Logical directory structure
- Easy to locate and modify functionality

### Testability
- Loosely coupled components
- Dependency injection pattern
- Pure functions in utilities
- Service classes can be mocked

### Scalability
- Batch processing for efficiency
- Configurable batch sizes
- Database tracking prevents reprocessing
- Video frame sampling for performance

## Configuration

All configuration is managed through environment variables. See README.md for the full
list; the main groups are email and SMTP, detection and batching, redaction
(`REDACTION_MODE`, `REDACTION_STRENGTH`, `REDACTION_PADDING`), Immich (`IMMICH_URL`,
`IMMICH_API_KEY`, `IMMICH_PATH_MAP`, `IMMICH_DELETE_MODE`) and the dashboard
(`DASHBOARD_*`, `REVIEW_*`).

Immich integration and the dashboard degrade independently: without Immich credentials the
service still scans, blurs and emails; without the dashboard the queue is simply not served.

## Dependencies

See `requirements.txt` for full list. Key dependencies:
- **nudenet**: AI model for content detection
- **opencv-python**: Image and video processing, blur and mosaic redaction
- **Pillow**: EXIF data extraction
- **watchdog**: File system monitoring
- **requests**: Immich API calls
- **Flask**: Moderation dashboard
- **waitress**: Production WSGI server for the dashboard
- **smtplib**: Email sending (built-in)

## Docker Deployment

The application is containerized with Docker:
- Base image: `python:3.13-bookworm`
- Volumes for data persistence, including retained dashboard previews
- The Immich library is mounted read-only; deletion only ever happens through the API
- Dashboard exposed on port 8080
- Environment-based configuration
- Health check polls the dashboard `/healthz` endpoint
