"""Main entry point for the Photo Moderation Service."""
import sys
from pathlib import Path

from src.config import Config
from src.services.scanner import Scanner
from src.services.moderator import Moderator
from src.services.notifier import Notifier
from src.services.watcher import MediaWatcher


def initial_scan(scanner, moderator, notifier, batch_size):
    """
    Perform an initial scan of existing files in the directory.

    Args:
        scanner: Scanner instance for tracking files
        moderator: Moderator instance for detection
        notifier: Notifier instance for sending alerts
        batch_size: Number of detections before sending batch
    """
    print("\n=== Running initial scan ===")

    batch = []
    processed_count = 0

    for file_path in scanner.get_new_files():
        print(f"Processing: {file_path}")
        processed_count += 1

        try:
            detections = moderator.detect(file_path)

            if moderator.is_explicit(detections):
                print(f"  Explicit content detected!")
                censored_result = moderator.censor(file_path, detections)

                if censored_result:
                    # Handle different return types (Path for images, list for videos)
                    if isinstance(censored_result, list):
                        for censored_path in censored_result:
                            batch.append({
                                'original_path': str(file_path),
                                'censored_path': censored_path,
                                'relative_path': Path(file_path).name,
                                'detections': detections
                            })
                    else:
                        batch.append({
                            'original_path': str(file_path),
                            'censored_path': censored_result,
                            'relative_path': Path(file_path).name,
                            'detections': detections
                        })

            # Mark as scanned
            scanner.mark_as_scanned(str(file_path))

            # Send batch if full
            if len(batch) >= batch_size:
                _send_batch(batch, notifier)
                batch = []

        except Exception as e:
            print(f"  Error processing {file_path}: {e}")

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
        for item in batch:
            censored_path = item['censored_path']
            if isinstance(censored_path, Path) and censored_path.exists():
                censored_path.unlink()


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
    print(f"Confidence threshold: {Config.CONFIDENCE_THRESHOLD}")

    # Initialize components
    scanner = Scanner(Config.SCAN_DIR, Config.DB_PATH)
    moderator = Moderator(Config.CENSORED_DIR, Config.CONFIDENCE_THRESHOLD)
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
        batch_size=Config.BATCH_SIZE
    )

    watcher.run()


if __name__ == '__main__':
    main()
