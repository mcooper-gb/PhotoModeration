"""Main entry point for the Photo Moderation Service."""
import sys

from src.config import Config
from src.services.scanner import Scanner
from src.services.moderator import Moderator
from src.services.notifier import Notifier
from src.services.watcher import MediaWatcher
from src.utils import cleanup_censored_files, process_media_file


def initial_scan(scanner, moderator, notifier, batch_size):
    """
    Perform an initial scan of existing files in the directory.

    Args:
        scanner: Scanner instance for tracking files
        moderator: Moderator instance for detection
        notifier: Notifier instance for sending alerts
        batch_size: Maximum number of detections before sending batch
    """
    print("\n=== Running initial scan ===")

    batch = []
    processed_count = 0

    for file_path in scanner.get_new_files():
        print(f"Processing: {file_path}")

        try:
            process_media_file(file_path, moderator, scanner, batch)

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
    Send a notification batch and clean up censored files.

    Args:
        batch: List of detection results to send
        notifier: Notifier instance
    """
    print(f"\nSending batch of {len(batch)} notifications...")

    if notifier.send_notification(batch):
        cleanup_censored_files(batch)


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

    # Initialize components
    scanner = Scanner(Config.SCAN_DIR, Config.DB_PATH)
    moderator = Moderator(
        Config.EXPLICIT_LABELS,
        Config.IMAGE_EXTENSIONS,
        Config.VIDEO_EXTENSIONS,
        Config.CENSORED_DIR,
        Config.CONFIDENCE_THRESHOLD
    )
    notifier = Notifier(
        Config.SMTP_SERVER,
        Config.SMTP_PORT,
        Config.SMTP_USER,
        Config.SMTP_PASS,
        Config.EMAIL_ADDRESS
    )

    # Run an initial scan of existing files
    initial_scan(scanner, moderator, notifier, Config.BATCH_SIZE)

    # Start watching for new files
    print("\n=== Starting file system watcher ===")
    watcher = MediaWatcher(
        Config.SCAN_DIR,
        scanner,
        moderator,
        notifier,
        batch_size=Config.BATCH_SIZE,
        batch_timeout=Config.BATCH_TIMEOUT
    )

    watcher.run()


if __name__ == '__main__':
    main()
