# Photo Moderation Service

Automated media scanning that detects explicit content in an Immich library, blurs the
offending regions, identifies who uploaded the asset, and gives moderators a dashboard to
work through the queue — including deleting any user's asset the same way Immich itself
does, so the Immich database and library stay consistent.

## How It Works

1. **Continuous Monitoring** - Watches the library directory and processes new media as it lands
2. **Explicit Content Detection** - Uses the NudeNet AI model to analyse images and video frames
3. **Blur Redaction** - Detected regions are blurred (or pixelated) rather than covered with a black box
4. **Immich Lookup** - Matches each file to its Immich asset and the user who uploaded it
   (one admin covers every user; no per-user API keys)
5. **Email Notifications** - Sends batched alerts with the redacted preview, the uploader, a review link and an Immich link
6. **Moderation Dashboard** - A web queue of every flagged item, redacted by default, with reveal, keep and delete actions
7. **Safe Deletion** - Applies Immich's own delete (trash by default), optionally emailing the uploader
8. **Duplicate Prevention** - Tracks processed files in SQLite to avoid re-scanning

## Immich Integration

### Admin moderation (recommended)

One admin moderates every user's uploads, and no user has to hand over an API key.

This needs database access, because the Immich API cannot do it. Immich API keys are scoped
to the user that created them: there is no admin permission for another user's asset (the
API exposes `adminUser`, `adminSession` and `adminConfig` permissions, but nothing for
assets), no `/admin/assets` endpoint, and no impersonation — `POST /sessions` and
`POST /api-keys` both act only on the caller. An admin key gets `400`/`403` on anyone
else's asset.

```dotenv
IMMICH_DB_HOST=immich-postgres
IMMICH_DB_NAME=immich
IMMICH_DB_USER=photomod
IMMICH_DB_PASSWORD=a-strong-password
IMMICH_EXTERNAL_URL=https://photos.example.com
IMMICH_PATH_MAP=/data/scan:upload/library
```

`IMMICH_DB_URL` can be used instead of the individual settings.

### Give the service its own restricted database role

Do not point it at the `postgres` superuser. Create a role that can read what it needs and
write only the two columns Immich's own delete touches:

```sql
CREATE USER photomod WITH PASSWORD 'a-strong-password';
GRANT CONNECT ON DATABASE immich TO photomod;
GRANT USAGE ON SCHEMA public TO photomod;
GRANT SELECT ON asset, "user" TO photomod;
GRANT UPDATE (status, "deletedAt") ON asset TO photomod;
```

On Immich versions that still use the plural table names, use `assets` and `users` instead
— the service detects which naming your schema uses at startup, and refuses to start in
admin mode if the columns it needs are missing, naming them in the log.

With that role the service cannot delete rows, rewrite paths, change users, or alter the
schema, even if it is compromised.

### What deletion actually does

Immich's own delete sets two columns (`AssetService.deleteAll`), and this service sets
exactly the same ones, so a moderated asset ends up in the same state as one the owner
deleted themselves:

| Action | Row state | Result |
|---|---|---|
| Move to trash | `status='trashed'`, `deletedAt=now()` | Leaves the timeline, appears in the owner's trash, restorable; Immich purges it when its trash retention expires |
| Delete permanently | `status='deleted'` | Gone from Immich immediately, as if the owner emptied their trash; Immich's own cleanup job removes the files, thumbnails and rows on its next run |

This service never deletes a file from disk and never deletes a database row — all of that
stays with Immich's background jobs. The `updatedAt`/`updateId` trigger fires on the
update, so clients pick the change up through normal sync.

### API key (optional)

An API key adds nothing for moderation, but if you set one the service will read Immich's
configured trash retention and can fall back to API lookups when the database is not
configured. In Immich: **Account Settings → API Keys → New API Key**, with:

| Permission | Used for |
|---|---|
| `asset.read` | Asset details and metadata search |
| `asset.upload` | Checksum lookup via the duplicate check endpoint |
| `asset.view` | Preview fallback in the dashboard |
| `asset.download` | Showing the original when a moderator reveals it |
| `asset.delete` | Deleting the key owner's own assets |
| `user.read` | Resolving the uploader's name and email |
| `adminConfig.read` | Reading the trash retention |

Without database access, deletion only works for assets owned by the key's own user. As a
fallback you can supply a key per user, but this is no longer the recommended setup:

```dotenv
IMMICH_API_KEYS_FILE=/data/db/immich-keys.json
```

```json
{
  "user-uuid-or-email": "that-user's-api-key"
}
```

### How assets are matched

With database access, each flagged file is matched on its original path, then its SHA1
checksum, then its filename (a filename that matches more than one asset is rejected rather
than guessed). Without it, the API equivalents are used: the asset UUID in the filename, a
checksum lookup via `POST /api/assets/bulk-upload-check`, then `POST /api/search/metadata`.

If nothing matches, the uploader is still recovered from the library path, which contains
the user id or storage label under Immich's default storage template.

Mount the Immich library read-only — the service only ever reads from it.

## Moderation Dashboard

Available on port 8080 by default.

- **Queue overview** with counts for pending, kept, deleted and failed items
- **Redacted previews everywhere by default** — the original is only loaded when a
  moderator explicitly chooses "Reveal original" (set `DASHBOARD_ALLOW_REVEAL=false` to
  remove the option entirely)
- **Uploader details** — name, email, Immich user id and how the asset was matched
- **Open in Immich** link to the asset (Immich shows an asset only to the user who owns it,
  so use the dashboard's own view to review someone else's upload)
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

# Immich (admin moderation over every user's uploads)
IMMICH_LIBRARY=/mnt/immich/library
IMMICH_EXTERNAL_URL=https://photos.example.com
IMMICH_PATH_MAP=/data/scan:upload/library
IMMICH_DELETE_MODE=trash
IMMICH_DB_HOST=immich-postgres
IMMICH_DB_NAME=immich
IMMICH_DB_USER=photomod
IMMICH_DB_PASSWORD=a-strong-password

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

- `IMMICH_DB_HOST` / `IMMICH_DB_PORT` - Immich PostgreSQL host and port (default port: 5432)
- `IMMICH_DB_NAME` / `IMMICH_DB_USER` / `IMMICH_DB_PASSWORD` - Database, role and password
- `IMMICH_DB_URL` - Full connection URL, used instead of the settings above
- `IMMICH_DB_TIMEOUT` - Connection timeout in seconds (default: 10)
- `IMMICH_EXTERNAL_URL` - Public Immich URL used in links
- `IMMICH_PATH_MAP` - `local:immich` path prefix pairs, comma separated
- `IMMICH_DELETE_MODE` - `trash` (default, recoverable) or `permanent`
- `IMMICH_NOTIFY_OWNER_DEFAULT` - Pre-tick the notify-uploader checkbox (default: false)
- `IMMICH_URL` - Internal Immich URL, only needed for the optional API fallback
- `IMMICH_API_KEY` - Immich API key (optional, see above)
- `IMMICH_API_KEYS_FILE` - Optional JSON file of per-user API keys (fallback only)
- `IMMICH_TIMEOUT` - API timeout in seconds (default: 15)
- `IMMICH_VERIFY_SSL` - Verify TLS certificates (default: true)

Immich integration stays off until either `IMMICH_DB_*` or `IMMICH_URL` plus
`IMMICH_API_KEY` is set; without it the service still scans, blurs and emails, but cannot
name the uploader or delete assets. Only the database settings give one admin control over
every user's uploads.

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
