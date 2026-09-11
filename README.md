# Photo Moderation Service

Automated media scanning that detects explicit content in an Immich library, blurs the
offending regions, identifies who uploaded the asset, and gives moderators a dashboard to
work through the queue — including deleting assets through the Immich API so the Immich
database stays consistent.

## How It Works

1. **Continuous Monitoring** - Watches the library directory and processes new media as it lands
2. **Explicit Content Detection** - Uses the NudeNet AI model to analyse images and video frames
3. **Blur Redaction** - Detected regions are blurred (or pixelated) rather than covered with a black box
4. **Immich Lookup** - Matches each file to its Immich asset and the user who uploaded it
5. **Email Notifications** - Sends batched alerts with the redacted preview, the uploader, a review link and an Immich link
6. **Moderation Dashboard** - A web queue of every flagged item, redacted by default, with reveal, keep and delete actions
7. **Safe Deletion** - Deletes through the Immich API (trash by default), optionally emailing the uploader
8. **Duplicate Prevention** - Tracks processed files in SQLite to avoid re-scanning

## Immich Integration

### 1. Create an API key

In Immich: **Account Settings → API Keys → New API Key**. The service needs these permissions:

| Permission | Used for |
|---|---|
| `asset.read` | Asset details and metadata search |
| `asset.upload` | Checksum lookup via the duplicate check endpoint |
| `asset.view` | Preview fallback in the dashboard |
| `asset.download` | Showing the original when a moderator reveals it |
| `asset.delete` | Trashing or permanently deleting a flagged asset |
| `user.read` | Resolving the uploader's name and email |

### 2. Mount the library and point at Immich

```dotenv
IMMICH_URL=http://immich-server:2283
IMMICH_EXTERNAL_URL=https://photos.example.com
IMMICH_API_KEY=your-immich-api-key
IMMICH_PATH_MAP=/data/scan:upload/library
```

`IMMICH_PATH_MAP` maps the path this service sees onto the path Immich stores internally.
Mount the Immich library read-only — files are never deleted from disk, only through the API.

### 3. How assets are matched

Each flagged file is matched to an Immich asset by trying, in order:

1. The asset UUID in the filename (Immich's own storage layout)
2. A SHA1 checksum lookup (`POST /api/assets/bulk-upload-check`)
3. The original path (`POST /api/search/metadata`)
4. The original filename, confirmed by checksum

If none match, the uploader is still recovered from the library path, which contains the
user id or storage label under Immich's default storage template.

### Deleting other users' assets

Immich API keys are scoped to the user that created them, so an admin key cannot delete
another user's asset. To moderate a multi-user library, supply a key per user:

```dotenv
IMMICH_API_KEYS_FILE=/data/db/immich-keys.json
```

```json
{
  "user-uuid-or-email": "that-user's-api-key"
}
```

The service uses the owner's key when one is configured, and the default key otherwise.

## Moderation Dashboard

Available on port 8080 by default.

- **Queue overview** with counts for pending, kept, deleted and failed items
- **Redacted previews everywhere by default** — the original is only loaded when a
  moderator explicitly chooses "Reveal original" (set `DASHBOARD_ALLOW_REVEAL=false` to
  remove the option entirely)
- **Uploader details** — name, email, Immich user id and how the asset was matched
- **Open in Immich** link to the asset in the Immich web app
- **Keep** to mark an item reviewed, or **Delete asset** to remove it from Immich
  (trash by default, permanent optional) with an optional email to the uploader
- **Restore from trash** for trashed items
- Video detections show the redacted frame; the original frame is re-extracted from the
  source on demand, so unredacted stills are never written to disk

Protect it with HTTP basic auth — it can display explicit content:

```dotenv
DASHBOARD_USER=moderator
DASHBOARD_PASS=a-strong-password
```

## Installation

### Using Docker Compose (Recommended)

1. **Clone or copy the project files to your machine**

2. **Create a `.env` file** in the project directory:

```dotenv
# Email
EMAIL_ADDRESS=recipient@example.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASS=your-app-password
BATCH_SIZE=10
BATCH_TIMEOUT=60
CONFIDENCE_THRESHOLD=0.6

# Immich
IMMICH_LIBRARY=/mnt/immich/library
IMMICH_URL=http://immich-server:2283
IMMICH_EXTERNAL_URL=https://photos.example.com
IMMICH_API_KEY=your-immich-api-key
IMMICH_PATH_MAP=/data/scan:upload/library
IMMICH_DELETE_MODE=trash

# Dashboard
DASHBOARD_PORT=8080
DASHBOARD_URL=https://moderation.example.com
DASHBOARD_USER=moderator
DASHBOARD_PASS=a-strong-password
```

3. **Start the service:**
```bash
docker-compose up -d
```

### Using Published Docker Image

Replace `build: .` with `image: mcoopergb/photo-moderation:latest` in `docker-compose.yml`.

## Configuration

### Email

- `EMAIL_ADDRESS` - Recipient email for moderation alerts
- `SMTP_SERVER` - SMTP server address (default: smtp.gmail.com)
- `SMTP_PORT` - SMTP port (default: 587)
- `SMTP_USER` - SMTP username, also the From address for uploader notifications
- `SMTP_PASS` - SMTP password (use an app-specific password for Gmail)

### Detection and batching

- `BATCH_SIZE` - Number of detections per notification batch (default: 10)
- `BATCH_TIMEOUT` - Seconds to wait before sending an incomplete batch while watching (default: 60, 0 disables)
- `CONFIDENCE_THRESHOLD` - Detection confidence from 0.0 to 1.0 (default: 0.6)

### Redaction

- `REDACTION_MODE` - `blur` (default), `pixelate` or `box` (the original black rectangle)
- `REDACTION_STRENGTH` - 1 to 100, how heavy the blur or mosaic is (default: 60)
- `REDACTION_PADDING` - Pixels each detected region is expanded by before redacting (default: 8)

### Immich

- `IMMICH_URL` - Internal Immich URL the service calls
- `IMMICH_EXTERNAL_URL` - Public Immich URL used in links (default: `IMMICH_URL`)
- `IMMICH_API_KEY` - Immich API key
- `IMMICH_API_KEYS_FILE` - Optional JSON file of per-user API keys
- `IMMICH_PATH_MAP` - `local:immich` path prefix pairs, comma separated
- `IMMICH_DELETE_MODE` - `trash` (default, recoverable) or `permanent`
- `IMMICH_NOTIFY_OWNER_DEFAULT` - Pre-tick the notify-uploader checkbox (default: false)
- `IMMICH_TIMEOUT` - API timeout in seconds (default: 15)
- `IMMICH_VERIFY_SSL` - Verify TLS certificates (default: true)

Immich integration stays off until both `IMMICH_URL` and `IMMICH_API_KEY` are set; without
it the service still scans, blurs and emails, but cannot name the uploader or delete assets.

### Dashboard

- `DASHBOARD_ENABLED` - Serve the dashboard (default: true)
- `DASHBOARD_HOST` / `DASHBOARD_PORT` - Bind address and port (default: 0.0.0.0:8080)
- `DASHBOARD_URL` - Public base URL used in email links
- `DASHBOARD_USER` / `DASHBOARD_PASS` - Optional HTTP basic auth
- `DASHBOARD_ALLOW_REVEAL` - Allow viewing unredacted originals (default: true)
- `DASHBOARD_PAGE_SIZE` - Items per page (default: 24)
- `REVIEW_DIR` - Where retained redacted previews are stored
- `REVIEW_DB_PATH` - Review queue database path
- `REVIEW_RETENTION_DAYS` - Purge resolved items older than this on startup (default: 30, 0 disables)

## Usage

1. Point `IMMICH_LIBRARY` at your Immich library (or drop files in `./images`)
2. The service scans existing files, then watches for new ones
3. Explicit content is blurred and emailed to the moderator, and queued in the dashboard
4. Moderators work through the queue: keep, reveal, or delete via Immich

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
