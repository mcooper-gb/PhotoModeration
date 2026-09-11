"""Immich integration: identify the uploader of a flagged file and act on the asset.

Everything goes through the Immich database (see immich_db.py). The REST API
cannot moderate a shared library at all: API keys are scoped to the user that
created them, there is no admin permission for another user's asset, no
/admin/assets endpoint, and no impersonation, so an admin key is rejected on
anyone else's asset.
"""
import re
from pathlib import Path

UUID_PATTERN = re.compile(
    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
)


class Immich:
    """Resolves flagged files to Immich assets and applies moderation decisions."""

    def __init__(self, database, external_url=None, delete_mode='trash'):
        """
        Initialize the integration.

        Args:
            database: ImmichDatabase used for every lookup and write
            external_url: Public Immich URL used when building links
            delete_mode: 'trash' (recoverable) or 'permanent'
        """
        self.database = database
        self.external_url = (external_url or '').rstrip('/')
        self.delete_mode = delete_mode

    @property
    def available(self):
        """Whether the Immich database is usable."""
        return bool(self.database and self.database.available)

    # --- Asset resolution ------------------------------------------------

    def resolve_asset(self, file_path):
        """
        Find the Immich asset for a file on disk, along with its uploader.

        Args:
            file_path: Path to the local file

        Returns:
            dict: Asset context with keys 'asset_id', 'owner_id', 'owner_name',
                  'owner_email', 'link' and 'resolved_by'. Values may be None.
        """
        file_path = Path(file_path)
        context = {
            'asset_id': None,
            'owner_id': None,
            'owner_name': None,
            'owner_email': None,
            'link': None,
            'resolved_by': None,
        }

        if not self.available:
            return context

        resolved = self._safely(lambda: self.database.resolve_asset(file_path),
                                f"lookup for {file_path.name}")
        if resolved:
            context.update({
                'asset_id': resolved['asset_id'],
                'owner_id': resolved['owner_id'],
                'owner_name': resolved['owner_name'],
                'owner_email': resolved['owner_email'],
                'resolved_by': resolved['resolved_by'],
                'link': self.asset_link(resolved['asset_id']),
            })
            return context

        # The asset row was not found, but Immich's default storage template
        # puts the owner's user id or storage label in the path, so the
        # moderator can still be told whose upload this is.
        owner_id = self._owner_id_from_path(file_path)
        if owner_id:
            owner = self._safely(lambda: self.database.get_user(owner_id),
                                 f"user lookup for {owner_id}") or {}
            context.update({
                'owner_id': owner_id,
                'owner_name': owner.get('name'),
                'owner_email': owner.get('email'),
                'resolved_by': 'library-path',
            })

        return context

    def _owner_id_from_path(self, file_path):
        """Derive the owner from the library path, by user id or storage label."""
        parts = Path(file_path).parts

        for part in parts:
            if UUID_PATTERN.fullmatch(part):
                return part

        for part in parts:
            user_id = self._safely(lambda: self.database.user_id_for_storage_label(part),
                                   f"storage label lookup for {part}")
            if user_id:
                return user_id

        return None

    def asset_link(self, asset_id):
        """Build the Immich web link for an asset."""
        if not asset_id or not self.external_url:
            return None
        return f"{self.external_url}/photos/{asset_id}"

    # --- Moderation actions ----------------------------------------------

    def delete_asset(self, asset_id, permanent=None):
        """
        Delete an asset the way Immich itself does, leaving its data consistent.

        This works for every user's assets. The file is never removed from disk
        by this service - Immich's own background jobs do that.

        Args:
            asset_id: Immich asset id
            permanent: Override the configured delete mode

        Returns:
            tuple[bool, str]: Success flag and a human readable detail message
        """
        if not asset_id:
            return False, "No Immich asset id is associated with this detection"
        if not self.available:
            return False, "The Immich database is not available"

        if permanent is None:
            permanent = self.delete_mode == 'permanent'

        if permanent:
            return self.database.delete_asset(asset_id, self.database.trash_days())
        return self.database.trash_asset(asset_id)

    def restore_asset(self, asset_id):
        """
        Restore a trashed asset.

        Returns:
            tuple[bool, str]: Success flag and detail message
        """
        if not asset_id:
            return False, "No Immich asset id is associated with this detection"
        if not self.available:
            return False, "The Immich database is not available"

        return self.database.restore_asset(asset_id)

    @staticmethod
    def _safely(action, description):
        """Run a database call, logging rather than raising on failure."""
        try:
            return action()
        except Exception as e:
            print(f"  Immich database {description} failed: {e}")
            return None
