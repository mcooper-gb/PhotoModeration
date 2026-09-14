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
5. **Email Notifications** - Sends batched alerts with the redacted preview, the uploader and a link to the dashboard review page
6. **Moderation Dashboard** - A web queue of every flagged item, redacted by default, with reveal, keep and delete actions
7. **Safe Deletion** - Applies Immich's own delete (trash by default), optionally emailing the uploader
8. **Duplicate Prevention** - Tracks processed files in SQLite to avoid re-scanning

## Immich Integration

### Admin moderation

One admin moderates every user's uploads. No user has to hand over an API key, and the
service does not use the Immich API at all.

It connects to Immich's database instead, because the API cannot do this job. Immich API
keys are scoped to the user that created them: there is no admin permission for another
user's asset (the API exposes `adminUser`, `adminSession` and `adminConfig` permissions,
but nothing for assets), no `/admin/assets` endpoint, and no impersonation —
`POST /sessions` and `POST /api-keys` both act only on the caller. An admin key gets
`400`/`403` on anyone else's asset.

```dotenv
IMMICH_DB_HOST=immich-postgres
IMMICH_DB_NAME=immich
IMMICH_DB_USER=photomod
IMMICH_DB_PASSWORD=a-strong-password
IMMICH_EXTERNAL_URL=https://photos.example.com
IMMICH_PATH_MAP=/data/scan:upload/library
```

`IMMICH_DB_URL` can be used instead of the individual settings.

### Reaching the Immich database

If Immich runs in its own Compose project, its database is on that project's network and is
not reachable from this one by default. Uncomment the `networks` blocks in
`docker-compose.yml` and set `IMMICH_NETWORK` to the network Immich's postgres container is
on — `docker network ls` shows it, usually `<immich project>_default`:

```dotenv
IMMICH_NETWORK=immich_default
```

They ship commented out because Compose refuses to start at all when an external network it
cannot find is declared, and the rest of the service works without Immich.

If you add this service to Immich's own Compose file instead, it is already on that network
and nothing needs changing.

### Give the service its own restricted database role

Do not point it at the `postgres` superuser. Create a role that can read what it needs and
write only the two columns Immich's own delete touches:

```sql
CREATE USER photomod WITH PASSWORD 'a-strong-password';
GRANT CONNECT ON DATABASE immich TO photomod;
GRANT USAGE ON SCHEMA public TO photomod;
GRANT SELECT ON asset, "user" TO photomod;
GRANT UPDATE (status, "deletedAt") ON asset TO photomod;

-- Optional: lets the service read your configured trash retention instead of
-- assuming Immich's 30 day default.
GRANT SELECT ON system_metadata TO photomod;
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

### How assets are matched

Each flagged file is matched on its original path, then its SHA1 checksum, then its
filename. A filename matching more than one asset is rejected rather than guessed, and
a filename match only names the uploader: it never links an asset that could be deleted,
because a filename says nothing about which asset a file is.

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
- Originals are read from the scanned library, so revealing one stops working if the file
  is removed or the mount goes away

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

## Upgrading from an earlier version

This release adds the Immich integration and the dashboard. There is no migration step,
but several things changed around it.

### What carries over

- **The scan tracking database is unchanged.** Files already scanned stay scanned and are
  not re-detected, so no email or dashboard item is produced for them again.
- **Nothing you reviewed before appears in the dashboard.** Earlier versions had no review
  queue: they emailed and deleted the preview. There is no record to import, so the queue
  starts empty and fills only from detections made after the upgrade.
- Leftover files in `./censored` from earlier versions are never read again and can be
  deleted.

### When the whole library gets scanned

Tracking is keyed on the path *inside the container* (`/data/scan/...`) plus the file's
modification time and size. Whatever directory you mount there is what matters:

- Mounting the same directory you were already scanning, whether or not you now name it
  with `IMMICH_LIBRARY`, changes nothing. Every file is recognised and skipped.
- Pointing the service at your Immich library for the first time is a new set of files, so
  all of it is scanned on the first run. Expect a long initial pass and a batch email for
  every `BATCH_SIZE` detections — `BATCH_TIMEOUT` does not apply during the initial scan,
  so raising `BATCH_SIZE` is what keeps the moderator's inbox manageable. The dashboard
  queue is unaffected either way.

Changing which directory is mounted also leaves the old rows in the tracking database.
They are harmless, and only match again if a file turns up at the same container path with
the same modification time and size.

An item that has already been reviewed returns to the queue as pending if its file is
detected again — the file was modified, or the tracking database was lost. A modified file
is genuinely new content, so this is deliberate.

### Settings that changed

Removed, and ignored if left in your `.env`: `IMMICH_URL`, `IMMICH_API_KEY`,
`IMMICH_API_KEYS_FILE`, `IMMICH_TIMEOUT`, `IMMICH_VERIFY_SSL`. Nothing fails on startup —
the log says `Immich integration disabled` — so check for that line if you expected the
Immich features to be on.

`DASHBOARD_USER` set with an empty `DASHBOARD_PASS` now refuses to start, rather than
running a dashboard that accepts any password.

### Compose changes to carry across

If you kept your own `docker-compose.yml`, add:

- `ports` for the dashboard, otherwise it runs unreachable
- a volume at `/data/review`, otherwise retained previews are written into the container
  and disappear when it is recreated, leaving the queue rows with broken images
- the `IMMICH_DB_*` settings, and network access to Immich's PostgreSQL

The image also needs rebuilding or repulling: `Flask`, `waitress` and `psycopg` are new
dependencies, and `requests` is gone.

The `nudenet-models` volume at `/root/.NudeNet` can be dropped. NudeNet ships its model
inside the Python package, so nothing was ever downloaded into it.

### The container no longer runs as root

From 1.2.1 the service runs as uid/gid `10001` instead of root, so that a malicious photo
that finds a bug in the image or video decoder does not get root inside the container.
The decoders are native code and every file the service reads is untrusted, so this is
worth the one-time upgrade step below.

Docker stamps that ownership onto a volume only when it creates it, so a **fresh install
needs nothing**. Volumes created by an earlier version are owned by root, and the service
cannot write to them until you hand them over. With the stack stopped:

```bash
docker compose run --rm --user root photo-moderation \
    chown -R 10001:10001 /data/db /data/review /data/censored
```

If you bind-mount rather than use the named volumes, chown the host directories instead —
`sudo chown -R 10001:10001 ./censored`. The scan directory is mounted read-only and needs
no change.

Symptoms of skipping this are `Permission denied` on startup or an empty dashboard queue
whose previews never appear. To stay on root instead, set `user: root` on the service in
`docker-compose.yml`; the image still works, it just gives up the hardening.

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

Immich integration stays off until `IMMICH_DB_*` is set; without it the service still
scans, blurs and emails, but cannot name the uploader or delete assets.

### Dashboard

- `DASHBOARD_ENABLED` - Serve the dashboard (default: true)
- `DASHBOARD_HOST` / `DASHBOARD_PORT` - Bind address and port (default: 0.0.0.0:8080).
  Compose publishes `DASHBOARD_PORT` on the host as well, so it is the same port inside
  and out
- `DASHBOARD_URL` - Public base URL used in email links
- `DASHBOARD_USER` / `DASHBOARD_PASS` - Optional HTTP basic auth (setting the user without a password is refused at startup)
- `DASHBOARD_ALLOW_REVEAL` - Allow viewing unredacted originals (default: true)
- `DASHBOARD_PAGE_SIZE` - Items per page (default: 24)
- `REVIEW_DIR` - Where retained redacted previews are stored
- `REVIEW_DB_PATH` - Review queue database path
- `REVIEW_RETENTION_DAYS` - Purge resolved items older than this, at startup and every 6 hours (default: 30, 0 disables)

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
