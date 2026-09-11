"""Direct Immich database access, so an admin can moderate every user's assets.

Immich API keys are scoped to the user that created them: there is no admin
permission for reading or deleting another user's asset, and no impersonation
endpoint. Moderating a shared library therefore needs database access.

Writes are deliberately limited to the two columns Immich's own delete uses
(AssetService.deleteAll sets `status` and `deletedAt`), so trashing through
this module leaves exactly the same row state as trashing through the API or
the web UI. File removal, thumbnails, search embeddings and row cleanup are
all left to Immich's own background jobs. Grant the service a role that can
only touch those columns - see README.md.
"""
import hashlib
import threading
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

STATUS_ACTIVE = 'active'
STATUS_TRASHED = 'trashed'
STATUS_DELETED = 'deleted'

# Immich renamed its tables to the singular form; support both.
ASSET_TABLES = ('asset', 'assets')
USER_TABLES = ('user', 'users')

REQUIRED_ASSET_COLUMNS = {'id', 'ownerId', 'originalPath', 'originalFileName', 'checksum',
                          'status', 'deletedAt'}
REQUIRED_USER_COLUMNS = {'id', 'name', 'email'}

# Only non-default settings are stored here, and the role may not be able to read it.
CONFIG_TABLE = 'system_metadata'
CONFIG_KEY = 'system-config'
DEFAULT_TRASH_DAYS = 30


class ImmichDatabaseError(Exception):
    """Raised when the Immich database cannot be used."""


class ImmichDatabase:
    """Reads asset ownership and applies Immich's own soft-delete states."""

    def __init__(self, dsn, path_map=None, connect_timeout=10):
        """
        Initialize the database client.

        Args:
            dsn: PostgreSQL connection string
            path_map: List of (local_prefix, immich_prefix) tuples
            connect_timeout: Connection timeout in seconds
        """
        self.dsn = dsn
        self.path_map = path_map or []
        self.connect_timeout = connect_timeout
        self.asset_table = None
        self.user_table = None
        self.has_storage_label = False
        self.lock = threading.Lock()
        self._trash_days = None

    def _connect(self):
        return psycopg.connect(self.dsn, connect_timeout=self.connect_timeout, row_factory=dict_row)

    def verify(self):
        """
        Check the connection and detect the schema this Immich version uses.

        Returns:
            bool: True when the database is usable for moderation
        """
        try:
            with self._connect() as conn:
                self.asset_table = self._detect_table(conn, ASSET_TABLES, REQUIRED_ASSET_COLUMNS)
                self.user_table = self._detect_table(conn, USER_TABLES, REQUIRED_USER_COLUMNS)
                self.has_storage_label = self._has_column(conn, self.user_table, 'storageLabel')
        except (psycopg.Error, ImmichDatabaseError) as e:
            print(f"Immich database unavailable: {e}")
            self.asset_table = self.user_table = None
            return False

        print(f"Connected to the Immich database (tables: {self.asset_table}, {self.user_table})")
        return True

    @property
    def available(self):
        """Whether verify() found a usable schema."""
        return bool(self.asset_table and self.user_table)

    @staticmethod
    def _detect_table(conn, candidates, required_columns):
        """Find which of the candidate table names exists with the columns we need."""
        for table in candidates:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                (table,)
            ).fetchall()

            if not rows:
                continue

            columns = {row['column_name'] for row in rows}
            missing = required_columns - columns
            if missing:
                raise ImmichDatabaseError(
                    f"table '{table}' is missing expected columns: {', '.join(sorted(missing))}"
                )
            return table

        raise ImmichDatabaseError(f"none of these tables exist: {', '.join(candidates)}")

    @staticmethod
    def _has_column(conn, table, column):
        """Check for a column this service can use but does not require."""
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
            (table, column)
        ).fetchone()
        return row is not None

    def _require_schema(self):
        if not self.available:
            raise ImmichDatabaseError("the Immich database schema has not been verified")

    def resolve_asset(self, file_path):
        """
        Find the Immich asset for a file on disk, along with its owner.

        Tries the original path as Immich stores it, then the file's SHA1
        checksum, then the filename.

        Args:
            file_path: Path to the local file

        Returns:
            dict or None: Asset context with 'asset_id', 'owner_id',
            'owner_name', 'owner_email' and 'resolved_by'
        """
        self._require_schema()

        immich_path = self.to_immich_path(file_path)
        checksum = sha1_digest(file_path)
        filename = str(file_path).rsplit('/', 1)[-1]

        attempts = []
        if immich_path:
            attempts.append(('db-original-path', '"originalPath" = %s', (immich_path,)))
        if checksum:
            attempts.append(('db-checksum', 'checksum = %s', (checksum,)))
        attempts.append(('db-filename', '"originalFileName" = %s', (filename,)))

        with self._connect() as conn:
            for strategy, clause, params in attempts:
                rows = conn.execute(
                    f'SELECT a.id, a."ownerId", a.status, u.name, u.email '
                    f'FROM "{self.asset_table}" a '
                    f'JOIN "{self.user_table}" u ON u.id = a."ownerId" '
                    f'WHERE a.{clause} LIMIT 2',
                    params
                ).fetchall()

                # Too risky to act on the wrong user's asset.
                if len(rows) != 1:
                    continue

                row = rows[0]
                return {
                    'asset_id': str(row['id']),
                    'owner_id': str(row['ownerId']),
                    'owner_name': row['name'],
                    'owner_email': row['email'],
                    'status': row['status'],
                    'resolved_by': strategy,
                }

        return None

    def find_user_for_path(self, file_path):
        """
        Identify the uploader from the library path, for a file with no asset row.

        Immich's default storage template names the directory after the owner's
        user id or storage label, so both are matched in one query. Comparing
        the id as text means an ordinary directory name is simply a non-match
        rather than a malformed-uuid error, so no shape check is needed first.

        Args:
            file_path: Path to the local file

        Returns:
            dict or None: User with 'id', 'name' and 'email', or None when
            nothing matched or more than one user did
        """
        self._require_schema()

        segments = self._library_segments(file_path)
        if not segments:
            return None

        clauses = ['lower(id::text) = ANY(%s)']
        params = [[segment.lower() for segment in segments]]

        if self.has_storage_label:
            clauses.append('"storageLabel" = ANY(%s)')
            params.append(segments)

        with self._connect() as conn:
            rows = conn.execute(
                f'SELECT id, name, email FROM "{self.user_table}" '
                f'WHERE {" OR ".join(clauses)} LIMIT 2',
                params
            ).fetchall()

        # Two matches means the path is ambiguous.
        if len(rows) != 1:
            return None

        row = rows[0]
        return {'id': str(row['id']), 'name': row['name'], 'email': row['email']}

    def _library_segments(self, file_path):
        """
        Return the directory names to match a user against.

        Only directories inside the mapped library are considered, so a mount
        point that happens to share a name with someone's storage label cannot
        be mistaken for it. The file name itself is never a candidate.
        """
        path_str = str(Path(file_path))

        for local_prefix, _ in self.path_map:
            if path_str.startswith(local_prefix):
                relative = Path(path_str[len(local_prefix):].lstrip('/'))
                return [part for part in relative.parts[:-1]]

        return [part for part in Path(path_str).parts[:-1] if part != '/']

    def trash_days(self):
        """
        Read Immich's configured trash retention.

        Immich only stores settings that differ from its defaults, and the
        table may not be readable by the moderation role, so this falls back
        to Immich's own default.

        Returns:
            int: Retention in days
        """
        if self._trash_days is not None:
            return self._trash_days

        self._trash_days = DEFAULT_TRASH_DAYS
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f'SELECT value FROM "{CONFIG_TABLE}" WHERE key = %s', (CONFIG_KEY,)
                ).fetchone()

            trash = ((row or {}).get('value') or {}).get('trash') or {}
            if trash.get('days'):
                self._trash_days = int(trash['days'])
        except (psycopg.Error, AttributeError, TypeError, ValueError) as e:
            print(f"Could not read Immich's trash retention, assuming "
                  f"{DEFAULT_TRASH_DAYS} days: {e}")

        return self._trash_days

    def get_asset_status(self, asset_id):
        """Return the current status of an asset, or None if it is gone."""
        self._require_schema()

        with self._connect() as conn:
            row = conn.execute(
                f'SELECT status FROM "{self.asset_table}" WHERE id = %s', (asset_id,)
            ).fetchone()

        return row['status'] if row else None

    def to_immich_path(self, file_path):
        """Translate a locally mounted path into the path Immich stores."""
        path_str = str(file_path)
        for local_prefix, immich_prefix in self.path_map:
            if path_str.startswith(local_prefix):
                suffix = path_str[len(local_prefix):].lstrip('/')
                return f"{immich_prefix}/{suffix}"
        return None

    def trash_asset(self, asset_id):
        """
        Move an asset to its owner's trash.

        Sets the same columns as Immich's own delete, so the asset leaves the
        timeline, appears in the owner's trash, stays restorable, and is purged
        by Immich's scheduled cleanup once the trash retention expires.

        Returns:
            tuple[bool, str]: Success flag and a detail message
        """
        return self._set_status(
            asset_id, STATUS_TRASHED, deleted_at='now()',
            success_detail=("Asset moved to the owner's Immich trash "
                            "(restorable until Immich's trash retention expires)")
        )

    def delete_asset(self, asset_id, trash_days=30):
        """
        Delete an asset outright, as emptying the trash does.

        The row is marked deleted, which removes the asset from Immich
        everywhere, and `deletedAt` is backdated past the trash retention so
        Immich's own scheduled cleanup removes the files, thumbnails and rows
        on its next run. No file is ever deleted by this service.

        Args:
            asset_id: Immich asset id
            trash_days: Immich's configured trash retention in days

        Returns:
            tuple[bool, str]: Success flag and a detail message
        """
        backdate = max(1, int(trash_days) + 1)
        return self._set_status(
            asset_id, STATUS_DELETED,
            deleted_at=f"now() - interval '{backdate} days'",
            success_detail=("Asset deleted from Immich; its files are removed by "
                            "Immich's next scheduled cleanup")
        )

    def restore_asset(self, asset_id):
        """
        Restore a trashed asset.

        Returns:
            tuple[bool, str]: Success flag and a detail message
        """
        self._require_schema()

        try:
            with self.lock, self._connect() as conn:
                cursor = conn.execute(
                    f'UPDATE "{self.asset_table}" SET status = %s, "deletedAt" = NULL '
                    f'WHERE id = %s AND status = %s',
                    (STATUS_ACTIVE, asset_id, STATUS_TRASHED)
                )
                if cursor.rowcount == 0:
                    return False, "Asset is not in the trash, so it was not restored"
                conn.commit()
        except psycopg.Error as e:
            return False, f"Immich database restore failed: {e}"

        return True, "Asset restored from the Immich trash"

    def _set_status(self, asset_id, status, deleted_at, success_detail):
        """Apply one of Immich's asset status transitions."""
        self._require_schema()

        try:
            with self.lock, self._connect() as conn:
                cursor = conn.execute(
                    f'UPDATE "{self.asset_table}" '
                    f'SET status = %s, "deletedAt" = {deleted_at} '
                    f'WHERE id = %s',
                    (status, asset_id)
                )
                if cursor.rowcount == 0:
                    return False, "Asset no longer exists in Immich"
                conn.commit()
        except psycopg.Error as e:
            return False, f"Immich database update failed: {e}"

        return True, success_detail


def sha1_digest(file_path):
    """
    Compute the raw SHA1 digest Immich stores in its checksum column.

    Returns:
        bytes or None
    """
    digest = hashlib.sha1()
    try:
        with open(file_path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
    except OSError as e:
        print(f"Could not checksum {file_path}: {e}")
        return None

    return digest.digest()


def build_dsn(url=None, host=None, port=5432, name='immich', user='postgres', password=None):
    """
    Build a PostgreSQL connection string from the configured parts.

    Args:
        url: Complete connection URL, which takes precedence
        host: Database host
        port: Database port
        name: Database name
        user: Database user
        password: Database password

    Returns:
        str or None: Connection string, or None when nothing is configured
    """
    if url:
        return url
    if not host:
        return None

    return psycopg.conninfo.make_conninfo(
        host=host, port=port, dbname=name, user=user, password=password
    )
