"""Moderation dashboard: review, reveal, delete and notify from the browser."""
import mimetypes
import os
import secrets
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import cv2
from flask import Flask, Response, abort, flash, redirect, render_template, request, send_file, url_for

from src.services.review_store import STATUS_DELETED, STATUS_ERROR, STATUS_KEPT, STATUS_PENDING, STATUSES

STATUS_LABELS = {
    STATUS_PENDING: 'Pending review',
    STATUS_KEPT: 'Kept',
    STATUS_DELETED: 'Deleted',
    STATUS_ERROR: 'Action failed',
}


class Dashboard:
    """Serves the moderator queue and applies moderation decisions."""

    def __init__(self, review_store, immich=None, notifier=None, moderator=None,
                 allow_reveal=True, username=None, password=None, page_size=24,
                 delete_mode='trash', notify_owner_default=False,
                 host='0.0.0.0', port=8080):
        """
        Initialize the dashboard.

        Args:
            review_store: ReviewStore holding the flagged queue
            immich: Optional Immich integration used for deletion and restores
            notifier: Optional Notifier used to email asset owners
            moderator: Optional Moderator, used to re-extract video frames
            allow_reveal: Whether moderators may view the unredacted original
            username: Optional HTTP basic auth username
            password: Optional HTTP basic auth password
            page_size: Items shown per page
            delete_mode: Default delete mode, 'trash' or 'permanent'
            notify_owner_default: Pre-tick the notify-owner checkbox
            host: Bind address
            port: Bind port
        """
        self.review_store = review_store
        self.immich = immich
        self.notifier = notifier
        self.moderator = moderator
        self.allow_reveal = allow_reveal
        self.username = username
        self.password = password
        self.page_size = page_size
        self.delete_mode = delete_mode
        self.notify_owner_default = notify_owner_default
        self.host = host
        self.port = port

        self.app = Flask(__name__)
        self.app.secret_key = os.getenv('DASHBOARD_SECRET_KEY') or secrets.token_hex(16)
        self._register_routes()

    # --- Auth ------------------------------------------------------------

    def _auth_required(self, view):
        """Wrap a view with optional HTTP basic auth."""

        @wraps(view)
        def wrapper(*args, **kwargs):
            if not self.username:
                return view(*args, **kwargs)

            auth = request.authorization
            if (auth and auth.username == self.username
                    and secrets.compare_digest(auth.password or '', self.password or '')):
                return view(*args, **kwargs)

            return Response(
                'Authentication required', 401,
                {'WWW-Authenticate': 'Basic realm="Photo Moderation"'}
            )

        return wrapper

    # --- Routes ----------------------------------------------------------

    def _register_routes(self):
        app = self.app

        app.add_url_rule('/', 'index', self._auth_required(self.index))
        app.add_url_rule('/review/<int:item_id>', 'detail', self._auth_required(self.detail))
        app.add_url_rule('/review/<int:item_id>/preview', 'preview', self._auth_required(self.preview))
        app.add_url_rule('/review/<int:item_id>/original', 'original', self._auth_required(self.original))
        app.add_url_rule('/review/<int:item_id>/action', 'action',
                         self._auth_required(self.action), methods=['POST'])
        app.add_url_rule('/healthz', 'healthz', self.healthz)

    def index(self):
        """Render the queue overview."""
        status = request.args.get('status', STATUS_PENDING)
        if status not in STATUSES:
            status = None

        search = (request.args.get('q') or '').strip() or None
        page = max(1, request.args.get('page', default=1, type=int))
        offset = (page - 1) * self.page_size

        items = self.review_store.list(
            status=status, limit=self.page_size + 1, offset=offset, search=search
        )
        has_next = len(items) > self.page_size

        return render_template(
            'index.html',
            items=items[:self.page_size],
            counts=self.review_store.counts(),
            status=status,
            search=search or '',
            page=page,
            has_next=has_next,
            status_labels=STATUS_LABELS,
        )

    def detail(self, item_id):
        """Render a single flagged detection."""
        item = self.review_store.get(item_id)
        if not item:
            abort(404)

        # Redacted by default; the original is only shown when asked for.
        reveal = self.allow_reveal and request.args.get('reveal') == '1'

        can_notify = bool(self.notifier and item.get('owner_email'))
        if can_notify:
            notify_blocked = None
        elif not self.notifier:
            notify_blocked = 'email notifications are not configured'
        else:
            notify_blocked = 'no email address is known for this uploader'

        return render_template(
            'detail.html',
            item=item,
            reveal=reveal,
            original_available=self._original_available(item),
            allow_reveal=self.allow_reveal,
            immich_enabled=self.immich is not None,
            can_notify=can_notify,
            notify_blocked=notify_blocked,
            notify_default=self.notify_owner_default,
            delete_mode=self.delete_mode,
            status_labels=STATUS_LABELS,
        )

    def preview(self, item_id):
        """Serve the retained redacted preview."""
        item = self.review_store.get(item_id)
        if not item:
            abort(404)

        redacted_path = item.get('redacted_path')
        if redacted_path and Path(redacted_path).exists():
            return send_file(redacted_path, mimetype='image/jpeg')

        abort(404)

    def original(self, item_id):
        """Serve the unredacted original, when revealing is permitted."""
        if not self.allow_reveal:
            abort(403)

        item = self.review_store.get(item_id)
        if not item:
            abort(404)

        source = Path(item['original_path'])

        if item.get('media_type') == 'video' and item.get('frame_number') is not None:
            frame_bytes = self._video_frame(source, item['frame_number'])
            if frame_bytes:
                return Response(frame_bytes, mimetype='image/jpeg')

        if source.exists():
            mimetype = mimetypes.guess_type(source.name)[0] or 'application/octet-stream'
            return send_file(source, mimetype=mimetype)

        abort(404)

    def action(self, item_id):
        """Apply a moderation decision to a flagged detection."""
        if not self._same_origin():
            abort(403)

        item = self.review_store.get(item_id)
        if not item:
            abort(404)

        choice = request.form.get('action')
        notify = request.form.get('notify') == 'on'
        note = (request.form.get('note') or '').strip() or None

        if choice == 'keep':
            self.review_store.set_status(item_id, STATUS_KEPT, 'Kept by moderator')
            flash('Marked as reviewed and kept.', 'success')
        elif choice == 'delete':
            self._delete(item, notify, note, request.form.get('mode'))
        elif choice == 'restore':
            self._restore(item)
        else:
            flash('Unknown action.', 'error')

        return redirect(url_for('detail', item_id=item_id))

    @staticmethod
    def _same_origin():
        """
        Reject cross-site form posts.

        Basic auth credentials are replayed by the browser on any request, so
        the destructive routes check that the post came from this dashboard.
        """
        source = request.headers.get('Origin') or request.headers.get('Referer')
        if not source:
            return True

        return urlparse(source).netloc == request.host

    def healthz(self):
        """Liveness endpoint for container health checks."""
        return {'status': 'ok', 'queue': self.review_store.counts()}

    # --- Decisions -------------------------------------------------------

    def _delete(self, item, notify, note, mode=None):
        """Delete the asset through Immich and optionally notify its owner."""
        item_id = item['id']

        if not self.immich:
            self.review_store.set_status(item_id, STATUS_ERROR, 'Immich integration is not configured')
            flash('Immich is not configured, so the asset cannot be deleted safely.', 'error')
            return

        if not item.get('immich_asset_id'):
            self.review_store.set_status(
                item_id, STATUS_ERROR,
                'No Immich asset id was resolved for this file, so it was not deleted'
            )
            flash('This detection is not linked to an Immich asset, so nothing was deleted.', 'error')
            return

        permanent = (mode or self.delete_mode) == 'permanent'
        success, detail = self.immich.delete_asset(item['immich_asset_id'], permanent=permanent)

        if not success:
            self.review_store.set_status(item_id, STATUS_ERROR, detail)
            flash(f'Delete failed: {detail}', 'error')
            return

        notified = False
        if notify:
            if self.notifier:
                notified, notify_detail = self.notifier.send_owner_notification(
                    item, 'deleted' if permanent else 'trashed', note
                )
                detail = f"{detail}. {notify_detail}"
            else:
                detail = f"{detail}. Owner not notified: email is not configured"

        # A permanently deleted asset leaves nothing to restore, so the local
        # redacted copy goes too; trashed assets keep theirs for restores.
        self.review_store.set_status(
            item_id, STATUS_DELETED, detail,
            owner_notified=notified, drop_preview=permanent
        )
        flash(detail, 'success')

    def _restore(self, item):
        """Restore a trashed asset and return it to the queue."""
        if not self.immich or not item.get('immich_asset_id'):
            flash('Nothing to restore for this detection.', 'error')
            return

        success, detail = self.immich.restore_asset(item['immich_asset_id'])
        if success:
            self.review_store.set_status(item['id'], STATUS_PENDING, detail)
            flash(detail, 'success')
        else:
            self.review_store.set_status(item['id'], STATUS_ERROR, detail)
            flash(f'Restore failed: {detail}', 'error')

    @staticmethod
    def _original_available(item):
        """
        Report whether the unredacted original can still be served.

        Originals are read from the scanned library, so they are unavailable
        once the source file has been removed or unmounted.
        """
        return Path(item['original_path']).exists()

    def _video_frame(self, video_path, frame_number):
        """Re-extract a video frame so originals never need storing on disk."""
        if not self.moderator or not Path(video_path).exists():
            return None

        frame = self.moderator.extract_frame(video_path, frame_number)
        if frame is None:
            return None

        success, buffer = cv2.imencode('.jpg', frame)
        return buffer.tobytes() if success else None

    # --- Lifecycle -------------------------------------------------------

    def run(self):
        """Run the dashboard (blocking), preferring a production WSGI server."""
        print(f"\nModeration dashboard listening on http://{self.host}:{self.port}")

        try:
            from waitress import serve
        except ImportError:
            self.app.run(host=self.host, port=self.port, threaded=True, use_reloader=False)
            return

        serve(self.app, host=self.host, port=self.port, threads=8, _quiet=True)
