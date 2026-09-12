"""Main entry point for the Photo Moderation Service."""
import sys
import threading

from src.config import Config
from src.services.immich import Immich
from src.services.immich_db import ImmichDatabase, build_dsn
from src.services.moderator import Moderator
from src.services.notifier import Notifier
from src.services.review_store import ReviewStore
from src.services.scanner import Scanner
from src.services.watcher import MediaWatcher
from src.utils import cleanup_censored_files, process_media_file
from src.web.dashboard import Dashboard


def initial_scan(scanner, moderator, notifier, batch_size, immich=None, review_store=None,
                 dashboard_url=None):
    """
    Perform an initial scan of existing files in the directory.

    Args:
        scanner: Scanner instance for tracking files
        moderator: Moderator instance for detection
        notifier: Notifier instance for sending alerts
        batch_size: Maximum number of detections before sending batch
        immich: Optional Immich integration for asset and owner lookup
        review_store: Optional ReviewStore for the moderation dashboard
        dashboard_url: Optional dashboard base URL used in review links
    """
    print("\n=== Running initial scan ===")

    batch = []
    processed_count = 0

    for file_path in scanner.get_new_files():
        print(f"Processing: {file_path}")

        try:
            process_media_file(file_path, moderator, scanner, batch, immich, review_store, dashboard_url)

            if len(batch) >= batch_size:
                _send_batch(batch, notifier)
                batch = []

        except Exception as e:
            print(f"  Error processing {file_path}: {e}")

        finally:
            processed_count += 1

    # Send the remaining batch
    if batch:
        _send_batch(batch, notifier)

    print(f"\nInitial scan complete: {processed_count} files processed")


def _send_batch(batch, notifier):
    """
    Send a notification batch and clean up redacted previews.

    Args:
        batch: List of detection results to send
        notifier: Notifier instance
    """
    print(f"\nSending batch of {len(batch)} notifications...")

    if not notifier.send_notification(batch):
        print("  Notification failed; the detections remain in the review queue")

    # Cleaned up either way: there is no retry, and the dashboard holds its own
    # copy, so keeping these would leave explicit images on disk with no reader.
    cleanup_censored_files(batch)


def build_immich_database():
    """
    Connect to the Immich database, which is what gives the admin control over
    every user's assets.

    Returns:
        ImmichDatabase or None
    """
    if not Config.immich_enabled():
        return None

    database = ImmichDatabase(
        build_dsn(
            url=Config.IMMICH_DB_URL,
            host=Config.IMMICH_DB_HOST,
            port=Config.IMMICH_DB_PORT,
            name=Config.IMMICH_DB_NAME,
            user=Config.IMMICH_DB_USER,
            password=Config.IMMICH_DB_PASSWORD,
        ),
        path_map=Config.path_map(),
        connect_timeout=Config.IMMICH_DB_TIMEOUT,
    )

    return database if database.verify() else None


def build_immich():
    """
    Create the Immich integration when the database is configured.

    Returns:
        Immich or None
    """
    if not Config.immich_enabled():
        print("Immich integration disabled (set IMMICH_DB_* to enable)")
        return None

    database = build_immich_database()
    if not database:
        print("Immich integration unavailable: the database could not be used")
        return None

    print(f"Moderating every user's assets (delete mode: {Config.IMMICH_DELETE_MODE}, "
          f"Immich trash retention: {database.trash_days()} days)")

    return Immich(
        database,
        external_url=Config.IMMICH_EXTERNAL_URL,
        delete_mode=Config.IMMICH_DELETE_MODE,
    )


def start_dashboard(review_store, immich, notifier, moderator):
    """
    Start the moderation dashboard in a background thread.

    Args:
        review_store: ReviewStore backing the queue
        immich: Optional Immich integration
        notifier: Notifier used to email asset owners
        moderator: Moderator used to re-extract video frames

    Returns:
        Dashboard or None
    """
    if not Config.DASHBOARD_ENABLED:
        print("Dashboard disabled (DASHBOARD_ENABLED=false)")
        return None

    dashboard = Dashboard(
        review_store,
        immich=immich,
        notifier=notifier,
        moderator=moderator,
        allow_reveal=Config.DASHBOARD_ALLOW_REVEAL,
        username=Config.DASHBOARD_USER,
        password=Config.DASHBOARD_PASS,
        page_size=Config.DASHBOARD_PAGE_SIZE,
        delete_mode=Config.IMMICH_DELETE_MODE,
        notify_owner_default=Config.IMMICH_NOTIFY_OWNER_DEFAULT,
        host=Config.DASHBOARD_HOST,
        port=Config.DASHBOARD_PORT,
    )

    if not Config.DASHBOARD_USER:
        print("Warning: dashboard authentication is not configured (set DASHBOARD_USER/DASHBOARD_PASS)")

    thread = threading.Thread(target=dashboard.run, name='dashboard', daemon=True)
    thread.start()
    return dashboard


def main():
    """Run the photo moderation service as a file system watcher."""
    try:
        Config.validate()
    except ValueError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    print("=== Photo Moderation Service ===")
    print(f"Monitoring: {Config.SCAN_DIR}")
    print(f"Output: {Config.CENSORED_DIR}")
    print(f"Batch size: {Config.BATCH_SIZE}")
    print(f"Batch timeout: {Config.BATCH_TIMEOUT}s")
    print(f"Confidence threshold: {Config.CONFIDENCE_THRESHOLD}")
    print(f"Redaction: {Config.REDACTION_MODE} (strength {Config.REDACTION_STRENGTH})")

    # Initialize components
    scanner = Scanner(Config.SCAN_DIR, Config.DB_PATH)
    moderator = Moderator(
        Config.EXPLICIT_LABELS,
        Config.IMAGE_EXTENSIONS,
        Config.VIDEO_EXTENSIONS,
        Config.CENSORED_DIR,
        Config.CONFIDENCE_THRESHOLD,
        Config.REDACTION_MODE,
        Config.REDACTION_STRENGTH,
        Config.REDACTION_PADDING
    )
    notifier = Notifier(
        Config.SMTP_SERVER,
        Config.SMTP_PORT,
        Config.SMTP_USER,
        Config.SMTP_PASS,
        Config.EMAIL_ADDRESS,
        Config.DASHBOARD_URL if Config.DASHBOARD_ENABLED else None
    )

    immich = build_immich()

    review_store = ReviewStore(Config.REVIEW_DB_PATH, Config.REVIEW_DIR)
    purged = review_store.purge_resolved(Config.REVIEW_RETENTION_DAYS)
    if purged:
        print(f"Purged {purged} resolved review items older than {Config.REVIEW_RETENTION_DAYS} days")

    dashboard_url = Config.DASHBOARD_URL if Config.DASHBOARD_ENABLED else None
    start_dashboard(review_store, immich, notifier, moderator)

    # Run an initial scan of existing files
    initial_scan(scanner, moderator, notifier, Config.BATCH_SIZE, immich, review_store, dashboard_url)

    # Start watching for new files
    print("\n=== Starting file system watcher ===")
    watcher = MediaWatcher(
        Config.SCAN_DIR,
        scanner,
        moderator,
        notifier,
        batch_size=Config.BATCH_SIZE,
        batch_timeout=Config.BATCH_TIMEOUT,
        immich=immich,
        review_store=review_store,
        dashboard_url=dashboard_url,
        retention_days=Config.REVIEW_RETENTION_DAYS
    )

    watcher.run()


if __name__ == '__main__':
    main()
