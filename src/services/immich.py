"""Immich API client for asset lookup, ownership and safe deletion.

Endpoints follow the Immich OpenAPI spec (base path /api):
  GET  /assets/{id}              asset details (permission: asset.read)
  POST /assets/bulk-upload-check checksum -> asset id (permission: asset.upload)
  POST /search/metadata          path/filename lookup (permission: asset.read)
  GET  /users, /users/{id}       owner details (permission: user.read)
  GET  /assets/{id}/thumbnail    preview bytes (permission: asset.view)
  GET  /assets/{id}/original     original bytes (permission: asset.download)
  DELETE /assets                 trash or permanently delete (permission: asset.delete)
"""
import base64
import hashlib
import re
import threading
from pathlib import Path

import requests

UUID_PATTERN = re.compile(
    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
)


class ImmichError(Exception):
    """Raised when an Immich API call fails."""


class ImmichClient:
    """Talks to an Immich server on behalf of the moderation service."""

    def __init__(self, base_url=None, api_key=None, external_url=None, timeout=15, verify_ssl=True,
                 path_map=None, delete_mode='trash', user_api_keys=None, database=None):
        """
        Initialize the client.

        Args:
            base_url: Internal Immich URL, e.g. http://immich-server:2283
            api_key: Immich API key used for API requests
            external_url: Public Immich URL used when building links
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify TLS certificates
            path_map: List of (local_prefix, immich_prefix) tuples
            delete_mode: 'trash' (recoverable) or 'permanent'
            user_api_keys: Optional dict of user id/email -> API key
            database: Optional ImmichDatabase giving admin-wide moderation
        """
        self.base_url = (base_url or '').rstrip('/')
        self.api_url = f"{self.base_url}/api"
        self.api_key = api_key
        self.external_url = (external_url or base_url or '').rstrip('/')
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.path_map = path_map or []
        self.delete_mode = delete_mode
        self.user_api_keys = {str(k).lower(): v for k, v in (user_api_keys or {}).items()}
        self.database = database

        self.session = requests.Session()
        self._users_by_id = {}
        self._storage_labels = {}
        self._users_loaded = False
        self._trash_days = None
        self._lock = threading.Lock()

    @property
    def api_enabled(self):
        """Whether API calls can be made at all."""
        return bool(self.base_url and self.api_key)

    @property
    def admin_mode(self):
        """
        Whether every user's assets can be moderated.

        True when the Immich database is configured: API keys are scoped to a
        single user, so the database is the only way an admin can act on
        assets belonging to everyone else.
        """
        return bool(self.database and self.database.available)

    # --- HTTP plumbing ---------------------------------------------------

    def _request(self, method, path, api_key=None, **kwargs):
        """Send a request to the Immich API and return the parsed response."""
        if not self.api_enabled:
            raise ImmichError("the Immich API is not configured")

        url = f"{self.api_url}{path}"
        headers = kwargs.pop('headers', {})
        headers['x-api-key'] = api_key or self.api_key
        headers.setdefault('Accept', 'application/json')

        try:
            response = self.session.request(
                method, url, headers=headers, timeout=self.timeout,
                verify=self.verify_ssl, **kwargs
            )
        except requests.RequestException as e:
            raise ImmichError(f"{method} {path} failed: {e}") from e

        if response.status_code == 404:
            return None
        if not response.ok:
            raise ImmichError(f"{method} {path} returned {response.status_code}: {response.text[:200]}")

        if response.status_code == 204 or not response.content:
            return {}

        if response.headers.get('Content-Type', '').startswith('application/json'):
            return response.json()
        return response.content

    def ping(self):
        """Check that the Immich server is reachable."""
        if not self.api_enabled:
            return False

        try:
            return self._request('GET', '/server/ping') is not None
        except ImmichError as e:
            print(f"Immich ping failed: {e}")
            return False

    def trash_days(self):
        """
        Read Immich's trash retention, used when scheduling a permanent delete.

        Returns:
            int: Retention in days, defaulting to Immich's own default of 30
        """
        if self._trash_days is not None:
            return self._trash_days

        self._trash_days = 30
        if self.api_enabled:
            try:
                config = self._request('GET', '/admin/config') or {}
                trash = config.get('trash') or {}
                if trash.get('enabled') and trash.get('days'):
                    self._trash_days = int(trash['days'])
            except (ImmichError, TypeError, ValueError) as e:
                print(f"Could not read the Immich trash retention, assuming 30 days: {e}")

        return self._trash_days

    # --- Users -----------------------------------------------------------

    def _load_users(self, force=False):
        """Cache the user directory so owners can be named without asset access."""
        with self._lock:
            if self._users_loaded and not force:
                return

            if not self.api_enabled:
                self._users_loaded = True
                return

            users = []
            # Admin keys get storage labels too, which appear in library paths.
            for path in ('/admin/users', '/users'):
                try:
                    result = self._request('GET', path)
                except ImmichError as e:
                    print(f"Immich user lookup via {path} failed: {e}")
                    continue

                if isinstance(result, list) and result:
                    users = result
                    break

            for user in users:
                user_id = user.get('id')
                if not user_id:
                    continue
                self._users_by_id[user_id] = user
                label = user.get('storageLabel')
                if label:
                    self._storage_labels[label] = user_id

            self._users_loaded = True

    def get_user(self, user_id):
        """
        Look up a user by id, using the cached directory first.

        Returns:
            dict or None: User with 'id', 'name' and 'email'
        """
        if not user_id:
            return None

        self._load_users()
        if user_id in self._users_by_id:
            return self._users_by_id[user_id]

        try:
            user = self._request('GET', f'/users/{user_id}')
        except ImmichError as e:
            print(f"Immich user {user_id} lookup failed: {e}")
            return None

        if user:
            self._users_by_id[user_id] = user
        return user

    def user_id_for_storage_label(self, label):
        """Resolve a storage label (used in library paths) to a user id."""
        self._load_users()
        return self._storage_labels.get(label)

    def api_key_for_user(self, user_id):
        """
        Pick the API key to use for a given owner.

        Immich API keys are scoped to the user that created them, so deleting
        another user's asset needs that user's key when one is configured.
        """
        if not user_id:
            return self.api_key

        key = self.user_api_keys.get(str(user_id).lower())
        if key:
            return key

        user = self._users_by_id.get(user_id) or {}
        email = (user.get('email') or '').lower()
        return self.user_api_keys.get(email, self.api_key)

    # --- Asset resolution ------------------------------------------------

    def resolve_asset(self, file_path):
        """
        Find the Immich asset that corresponds to a file on disk.

        The database is asked first when it is configured, because it sees
        every user's assets. Otherwise the API is tried in order of cost: the
        asset UUID embedded in the filename, a SHA1 checksum lookup, then a
        path/filename search. Owner hints derived from the library path are
        used when neither can identify the asset.

        Args:
            file_path: Path to the local file

        Returns:
            dict: Asset context with keys 'asset_id', 'owner_id', 'owner_name',
                  'owner_email', 'link' and 'resolved_by'. Values may be None.
        """
        file_path = Path(file_path)
        context = {
            'asset_id': None,
            'owner_id': self._owner_id_from_path(file_path),
            'owner_name': None,
            'owner_email': None,
            'link': None,
            'resolved_by': None,
        }

        if self.admin_mode:
            resolved = self._resolve_via_database(file_path)
            if resolved:
                resolved['link'] = self.asset_link(resolved['asset_id'])
                return resolved

        asset = None
        for strategy, finder in (
            ('filename-uuid', self._asset_from_filename),
            ('checksum', self._asset_from_checksum),
            ('original-path', self._asset_from_path_search),
            ('filename-search', self._asset_from_filename_search),
        ):
            try:
                asset = finder(file_path)
            except ImmichError as e:
                print(f"Immich lookup ({strategy}) failed for {file_path.name}: {e}")
                asset = None

            if asset:
                context['resolved_by'] = strategy
                break

        if asset:
            context['asset_id'] = asset.get('id')
            context['owner_id'] = asset.get('ownerId') or context['owner_id']
            owner = asset.get('owner')
            if owner:
                context['owner_name'] = owner.get('name')
                context['owner_email'] = owner.get('email')
        elif context['owner_id']:
            # Path told us who owns it even though the asset is not readable.
            context['resolved_by'] = 'library-path'

        if not context['owner_name'] and context['owner_id']:
            user = self.get_user(context['owner_id'])
            if user:
                context['owner_name'] = user.get('name')
                context['owner_email'] = user.get('email')

        context['link'] = self.asset_link(context['asset_id'])
        return context

    def _resolve_via_database(self, file_path):
        """Look the asset up directly, which works for every user's library."""
        try:
            resolved = self.database.resolve_asset(file_path)
        except Exception as e:
            print(f"Immich database lookup failed for {file_path.name}: {e}")
            return None

        if not resolved:
            return None

        return {
            'asset_id': resolved['asset_id'],
            'owner_id': resolved['owner_id'],
            'owner_name': resolved['owner_name'],
            'owner_email': resolved['owner_email'],
            'link': None,
            'resolved_by': resolved['resolved_by'],
        }

    def _asset_from_filename(self, file_path):
        """Assets stored by Immich are named after their UUID."""
        match = UUID_PATTERN.fullmatch(file_path.stem)
        if not match:
            return None
        return self.get_asset(file_path.stem)

    def _asset_from_checksum(self, file_path):
        """Resolve via the bulk upload duplicate check, which takes a SHA1."""
        checksum = self.file_checksum(file_path)
        if not checksum:
            return None

        payload = {'assets': [{'id': file_path.name, 'checksum': checksum}]}
        result = self._request('POST', '/assets/bulk-upload-check', json=payload)

        for entry in (result or {}).get('results', []):
            asset_id = entry.get('assetId')
            if asset_id:
                return self.get_asset(asset_id) or {'id': asset_id}
        return None

    def _asset_from_path_search(self, file_path):
        """Search by the path as Immich stores it internally."""
        immich_path = self.to_immich_path(file_path)
        if not immich_path:
            return None

        items = self._search_metadata({'originalPath': immich_path})
        return items[0] if items else None

    def _asset_from_filename_search(self, file_path):
        """Last resort: match on filename and confirm with the checksum."""
        items = self._search_metadata({'originalFileName': file_path.name})
        if not items:
            return None

        checksum = self.file_checksum(file_path)
        for asset in items:
            if checksum and asset.get('checksum') == checksum:
                return asset

        return items[0] if len(items) == 1 else None

    def _search_metadata(self, criteria):
        """Run a metadata search and return the matching assets."""
        payload = dict(criteria)
        payload.setdefault('withDeleted', False)
        result = self._request('POST', '/search/metadata', json=payload)
        return ((result or {}).get('assets') or {}).get('items') or []

    def get_asset(self, asset_id, api_key=None):
        """Fetch asset details by id."""
        if not asset_id:
            return None
        return self._request('GET', f'/assets/{asset_id}', api_key=api_key)

    def _owner_id_from_path(self, file_path):
        """
        Derive the owner from the library path.

        Immich's default storage template writes to
        upload/library/<user id or storage label>/<date>/<file>, so the owner
        is usually recoverable from the path alone.
        """
        for part in Path(file_path).parts:
            if UUID_PATTERN.fullmatch(part):
                return part

        for part in Path(file_path).parts:
            user_id = self.user_id_for_storage_label(part)
            if user_id:
                return user_id

        return None

    def to_immich_path(self, file_path):
        """Translate a locally mounted path into the path Immich stores."""
        path_str = str(Path(file_path))
        for local_prefix, immich_prefix in self.path_map:
            if path_str.startswith(local_prefix):
                suffix = path_str[len(local_prefix):].lstrip('/')
                return f"{immich_prefix}/{suffix}"
        return None

    @staticmethod
    def file_checksum(file_path):
        """Compute the base64 encoded SHA1 checksum Immich uses for assets."""
        digest = hashlib.sha1()
        try:
            with open(file_path, 'rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
        except OSError as e:
            print(f"Could not checksum {file_path}: {e}")
            return None

        return base64.b64encode(digest.digest()).decode('ascii')

    # --- Links and media -------------------------------------------------

    def asset_link(self, asset_id):
        """Build the Immich web link for an asset."""
        if not asset_id or not self.external_url:
            return None
        return f"{self.external_url}/photos/{asset_id}"

    def fetch_thumbnail(self, asset_id, owner_id=None, size='preview'):
        """
        Download an asset preview.

        Returns:
            bytes or None
        """
        if not asset_id:
            return None

        try:
            return self._request(
                'GET', f'/assets/{asset_id}/thumbnail',
                api_key=self.api_key_for_user(owner_id),
                params={'size': size},
                headers={'Accept': 'image/*'},
            )
        except ImmichError as e:
            print(f"Immich thumbnail fetch failed for {asset_id}: {e}")
            return None

    def fetch_original(self, asset_id, owner_id=None):
        """
        Download the original asset bytes.

        Returns:
            bytes or None
        """
        if not asset_id:
            return None

        try:
            return self._request(
                'GET', f'/assets/{asset_id}/original',
                api_key=self.api_key_for_user(owner_id),
                headers={'Accept': '*/*'},
            )
        except ImmichError as e:
            print(f"Immich original fetch failed for {asset_id}: {e}")
            return None

    # --- Deletion --------------------------------------------------------

    def delete_asset(self, asset_id, owner_id=None, permanent=None):
        """
        Delete an asset the way Immich itself does, leaving its data consistent.

        With the database configured this works for every user's assets, which
        the API cannot do: Immich has no admin permission for another user's
        asset. Either way the file is never removed from disk by this service -
        Immich's own background jobs do that.

        Args:
            asset_id: Immich asset id
            owner_id: Owner id, used to pick a per-user API key if configured
            permanent: Override the configured delete mode

        Returns:
            tuple[bool, str]: Success flag and a human readable detail message
        """
        if not asset_id:
            return False, "No Immich asset id is associated with this detection"

        if permanent is None:
            permanent = self.delete_mode == 'permanent'

        if self.admin_mode:
            if permanent:
                return self.database.delete_asset(asset_id, self.trash_days())
            return self.database.trash_asset(asset_id)

        payload = {'ids': [asset_id], 'force': bool(permanent)}

        try:
            self._request('DELETE', '/assets', api_key=self.api_key_for_user(owner_id), json=payload)
        except ImmichError as e:
            return False, self._explain_api_failure(e)

        if permanent:
            return True, "Asset permanently deleted from Immich"
        return True, "Asset moved to the Immich trash (recoverable until the trash is emptied)"

    def restore_asset(self, asset_id, owner_id=None):
        """
        Restore a trashed asset.

        Returns:
            tuple[bool, str]: Success flag and detail message
        """
        if not asset_id:
            return False, "No Immich asset id is associated with this detection"

        if self.admin_mode:
            return self.database.restore_asset(asset_id)

        try:
            self._request(
                'POST', '/trash/restore/assets',
                api_key=self.api_key_for_user(owner_id),
                json={'ids': [asset_id]},
            )
        except ImmichError as e:
            return False, self._explain_api_failure(e)

        return True, "Asset restored from the Immich trash"

    @staticmethod
    def _explain_api_failure(error):
        """
        Add the likely cause to an API error.

        Immich rejects asset operations on assets the key's own user does not
        own, which is the usual reason moderation fails without database access.
        """
        detail = str(error)
        if any(code in detail for code in (' 400', ' 403')):
            detail += (". Immich API keys only cover their own user's assets; "
                       "configure IMMICH_DB_* so the admin can moderate every user")
        return detail
