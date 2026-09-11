"""Immich integration: identify the uploader of a flagged file and act on the asset.

Everything goes through the Immich database (see immich_db.py). The REST API
cannot moderate a shared library at all: API keys are scoped to the user that
created them, there is no admin permission for another user's asset, no
/admin/assets endpoint, and no impersonation, so an admin key is rejected on
anyone else's asset.
"""
from pathlib import Path


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

        # Immich's storage template names the directory after the owner, so
        # the uploader is identifiable even with no asset row.
        owner = self._safely(lambda: self.database.find_user_for_path(file_path),
                             f"uploader lookup for {file_path.name}")
        if owner:
            context.update({
                'owner_id': owner['id'],
                'owner_name': owner['name'],
                'owner_email': owner['email'],
                'resolved_by': 'library-path',
            })

        return context

    def asset_link(self, asset_id):
        """Build the Immich web link for an asset."""
        if not asset_id or not self.external_url:
            return None
        return f"{self.external_url}/photos/{asset_id}"

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
