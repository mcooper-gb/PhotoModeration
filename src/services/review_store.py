"""SQLite backed queue of flagged media awaiting moderator review."""
import hashlib
import json
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATUS_PENDING = 'pending'
STATUS_KEPT = 'kept'
STATUS_DELETED = 'deleted'
STATUS_ERROR = 'error'

STATUSES = (STATUS_PENDING, STATUS_KEPT, STATUS_DELETED, STATUS_ERROR)

# Images have no frame, but SQLite treats NULLs as distinct in unique
# constraints, so a sentinel keeps the upsert working on rescans.
NO_FRAME = -1


class ReviewStore:
    """Persist flagged detections so moderators can work through them."""

    def __init__(self, db_path, review_dir):
        """
        Initialize the store.

        Args:
            db_path: Path to the SQLite database file
            review_dir: Directory holding retained redacted previews
        """
        self.db_path = str(db_path)
        self.review_dir = Path(review_dir)
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS flagged_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    frame_number INTEGER NOT NULL DEFAULT -1,
                    frame_timestamp REAL,
                    redacted_path TEXT,
                    labels TEXT,
                    max_score REAL,
                    detections TEXT,
                    immich_asset_id TEXT,
                    immich_owner_id TEXT,
                    immich_link TEXT,
                    owner_name TEXT,
                    owner_email TEXT,
                    resolved_by TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    status_detail TEXT,
                    owner_notified INTEGER NOT NULL DEFAULT 0,
                    detected_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    UNIQUE (original_path, frame_number)
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON flagged_assets (status, detected_at DESC)')
            conn.commit()
        finally:
            conn.close()

    def add(self, original_path, redacted_path, detections, media_type, immich_context=None,
            frame_number=None, frame_timestamp=None):
        """
        Record a flagged detection, retaining a copy of the redacted preview.

        A rescan of the same file (and frame) updates the existing row and
        returns it to the pending queue.

        Args:
            original_path: Path to the source media file
            redacted_path: Path to the blurred preview produced by the moderator
            detections: Raw detection data
            media_type: 'image' or 'video'
            immich_context: Asset context from Immich.resolve_asset
            frame_number: Frame index for videos
            frame_timestamp: Frame timestamp in seconds for videos

        Returns:
            int: Review item id, or None if the item could not be stored
        """
        immich_context = immich_context or {}
        frame_key = NO_FRAME if frame_number is None else int(frame_number)
        labels, max_score = summarise_detections(detections)
        retained = self._retain_preview(redacted_path, original_path, frame_key)
        now = _utc_now()

        with self.lock:
            conn = self._connect()
            try:
                cursor = conn.execute('''
                    INSERT INTO flagged_assets (
                        original_path, file_name, media_type, frame_number, frame_timestamp,
                        redacted_path, labels, max_score, detections,
                        immich_asset_id, immich_owner_id, immich_link, owner_name, owner_email,
                        resolved_by, status, detected_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (original_path, frame_number) DO UPDATE SET
                        redacted_path = excluded.redacted_path,
                        labels = excluded.labels,
                        max_score = excluded.max_score,
                        detections = excluded.detections,
                        immich_asset_id = COALESCE(excluded.immich_asset_id, flagged_assets.immich_asset_id),
                        immich_owner_id = COALESCE(excluded.immich_owner_id, flagged_assets.immich_owner_id),
                        immich_link = COALESCE(excluded.immich_link, flagged_assets.immich_link),
                        owner_name = COALESCE(excluded.owner_name, flagged_assets.owner_name),
                        owner_email = COALESCE(excluded.owner_email, flagged_assets.owner_email),
                        resolved_by = excluded.resolved_by,
                        status = ?,
                        status_detail = NULL,
                        reviewed_at = NULL,
                        detected_at = excluded.detected_at
                    RETURNING id
                ''', (
                    str(original_path), Path(original_path).name, media_type, frame_key,
                    frame_timestamp, str(retained) if retained else None,
                    json.dumps(labels), max_score, json.dumps(_serialisable(detections)),
                    immich_context.get('asset_id'), immich_context.get('owner_id'),
                    immich_context.get('link'), immich_context.get('owner_name'),
                    immich_context.get('owner_email'), immich_context.get('resolved_by'),
                    STATUS_PENDING, now, STATUS_PENDING,
                ))
                row = cursor.fetchone()
                conn.commit()
                if row:
                    return row['id']

                # Fall back for SQLite builds without RETURNING support.
                existing = conn.execute(
                    'SELECT id FROM flagged_assets WHERE original_path = ? AND frame_number = ?',
                    (str(original_path), frame_key)
                ).fetchone()
                return existing['id'] if existing else None
            except sqlite3.Error as e:
                print(f"Failed to record review item for {original_path}: {e}")
                return None
            finally:
                conn.close()

    def get(self, item_id):
        """Return a single review item as a dict, or None."""
        conn = self._connect()
        try:
            row = conn.execute('SELECT * FROM flagged_assets WHERE id = ?', (item_id,)).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()

    def list(self, status=None, limit=24, offset=0, search=None):
        """
        List review items, newest first.

        Args:
            status: Filter by status, or None for all
            limit: Maximum rows to return
            offset: Rows to skip
            search: Optional substring matched against file name and owner

        Returns:
            list[dict]: Review items
        """
        query = 'SELECT * FROM flagged_assets'
        clauses = []
        params = []

        if status in STATUSES:
            clauses.append('status = ?')
            params.append(status)

        if search:
            clauses.append('(file_name LIKE ? OR owner_name LIKE ? OR owner_email LIKE ?)')
            params.extend([f'%{search}%'] * 3)

        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)

        query += ' ORDER BY datetime(detected_at) DESC, id DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def counts(self):
        """Return a count per status plus a 'total' entry."""
        conn = self._connect()
        try:
            rows = conn.execute('SELECT status, COUNT(*) AS total FROM flagged_assets GROUP BY status').fetchall()
        finally:
            conn.close()

        counts = {status: 0 for status in STATUSES}
        for row in rows:
            counts[row['status']] = row['total']
        counts['total'] = sum(counts[status] for status in STATUSES)
        return counts

    def set_status(self, item_id, status, detail=None, owner_notified=None, drop_preview=False):
        """
        Update the review state of an item.

        Args:
            item_id: Review item id
            status: One of STATUSES
            detail: Human readable outcome detail
            owner_notified: Whether the owner was emailed
            drop_preview: Delete the retained preview (used once content is gone)

        Returns:
            bool: True if a row was updated
        """
        item = self.get(item_id)
        if not item:
            return False

        fields = ['status = ?', 'status_detail = ?', 'reviewed_at = ?']
        params = [status, detail, _utc_now()]

        if owner_notified is not None:
            fields.append('owner_notified = ?')
            params.append(1 if owner_notified else 0)

        if drop_preview:
            _remove_file(item.get('redacted_path'))
            fields.append('redacted_path = NULL')

        params.append(item_id)

        with self.lock:
            conn = self._connect()
            try:
                conn.execute(f'UPDATE flagged_assets SET {", ".join(fields)} WHERE id = ?', params)
                conn.commit()
                return True
            finally:
                conn.close()

    def purge_resolved(self, older_than_days):
        """
        Delete resolved rows (and their previews) older than the retention window.

        Args:
            older_than_days: Retention window in days, 0 disables purging

        Returns:
            int: Number of rows removed
        """
        if not older_than_days:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()

        with self.lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT id, redacted_path FROM flagged_assets "
                    "WHERE status != ? AND reviewed_at IS NOT NULL AND reviewed_at < ?",
                    (STATUS_PENDING, cutoff)
                ).fetchall()

                for row in rows:
                    _remove_file(row['redacted_path'])

                if rows:
                    conn.executemany(
                        'DELETE FROM flagged_assets WHERE id = ?',
                        [(row['id'],) for row in rows]
                    )
                    conn.commit()

                return len(rows)
            finally:
                conn.close()

    def _retain_preview(self, redacted_path, original_path, frame_key):
        """Copy the redacted preview into the review directory so it outlives the email batch."""
        if not redacted_path:
            return None

        source = Path(redacted_path)
        if not source.exists():
            return None

        suffix = '' if frame_key == NO_FRAME else f"_f{frame_key}"
        digest = hashlib.sha1(str(original_path).encode('utf-8')).hexdigest()[:8]
        target = self.review_dir / f"{Path(original_path).stem}_{digest}{suffix}.jpg"

        try:
            shutil.copy2(source, target)
            return target
        except OSError as e:
            print(f"Failed to retain redacted preview for {original_path}: {e}")
            return None


def summarise_detections(detections):
    """
    Reduce detections to the labels found and the highest confidence score.

    Args:
        detections: List (image) or dict of frame -> list (video)

    Returns:
        tuple[list[str], float]: Sorted labels and the maximum score
    """
    if isinstance(detections, dict):
        flat = [det for frame in detections.values() if isinstance(frame, list) for det in frame]
    else:
        flat = list(detections or [])

    labels = {}
    for det in flat:
        label = det.get('class')
        if not label:
            continue
        score = float(det.get('score', 0))
        labels[label] = max(labels.get(label, 0), score)

    max_score = max(labels.values()) if labels else 0.0
    return sorted(labels.keys()), max_score


def _serialisable(detections):
    """Strip anything that cannot be stored as JSON."""
    try:
        json.dumps(detections)
        return detections
    except (TypeError, ValueError):
        return str(detections)


def _row_to_dict(row):
    """Convert a SQLite row into a plain dict, decoding JSON columns."""
    if row is None:
        return None

    item = dict(row)
    for key in ('labels', 'detections'):
        value = item.get(key)
        if isinstance(value, str):
            try:
                item[key] = json.loads(value)
            except (TypeError, ValueError):
                pass

    item['owner_notified'] = bool(item.get('owner_notified'))
    if item.get('frame_number') == NO_FRAME:
        item['frame_number'] = None

    return item


def _remove_file(path):
    """Delete a file if it exists, ignoring errors."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as e:
        print(f"Failed to remove {path}: {e}")


def _utc_now():
    return datetime.now(timezone.utc).isoformat()
