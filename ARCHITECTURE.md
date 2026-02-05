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
    │   ├── moderator.py        # Content detection and censoring
    │   ├── notifier.py         # Email notification service
    │   └── watcher.py          # File system watching
    │
    ├── utils/                  # Utility modules
    │   ├── __init__.py
    │   └── exif_extractor.py   # EXIF metadata extraction
    │
    └── templates/              # Email templates
        ├── __init__.py
        └── email_template.py   # HTML email generation
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
- Censors detected content by drawing black boxes
- Optimizes video processing with frame sampling

#### notifier.py
- Sends HTML email notifications
- Enriches detection data with EXIF metadata
- Embeds censored images inline in emails
- Handles SMTP communication

#### watcher.py
- Monitors directory for new files
- Triggers processing pipeline for new media
- Batches notifications for efficiency
- Manages cleanup of temporary censored files

### src/utils/

#### exif_extractor.py
- Extracts EXIF metadata from images
- Parses GPS coordinates
- Converts GPS data to decimal format
- Generates Google Maps links

### src/templates/

#### email_template.py
- Generates HTML email templates
- Applies CSS styling
- Creates structured email content with file details
- Handles inline image embedding

## Data Flow

1. **Initial Scan** (startup):
   - Scanner identifies unprocessed files
   - Moderator detects and censors explicit content
   - Notifier sends batch email notifications
   - Censored files are cleaned up

2. **File Watching** (ongoing):
   - Watcher monitors directory for new files
   - New files trigger the moderation pipeline
   - Results are batched and sent via email
   - Database tracks processed files

3. **Email Generation**:
   - Notifier enriches results with EXIF data
   - EmailTemplate generates styled HTML
   - Images embedded inline with Content-ID
   - Email sent via SMTP

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

All configuration is managed through environment variables:
- `SCAN_DIR`: Directory to monitor
- `CENSORED_DIR`: Output directory for censored content
- `DB_PATH`: SQLite database path
- `BATCH_SIZE`: Number of detections per notification batch
- `EMAIL_ADDRESS`: Recipient email
- `SMTP_SERVER`: SMTP server address
- `SMTP_PORT`: SMTP port
- `SMTP_USER`: SMTP username
- `SMTP_PASS`: SMTP password

## Dependencies

See `requirements.txt` for full list. Key dependencies:
- **nudenet**: AI model for content detection
- **opencv-python**: Image and video processing
- **Pillow**: EXIF data extraction
- **watchdog**: File system monitoring
- **smtplib**: Email sending (built-in)

## Docker Deployment

The application is containerized with Docker:
- Base image: `python:3.11-bookworm`
- Volumes for data persistence
- Environment-based configuration
- Health checks for monitoring
