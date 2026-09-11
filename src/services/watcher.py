import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.services.batch_manager import BatchManager
from src.utils import process_media_file


class MediaFileHandler(FileSystemEventHandler):
    """Handles file system events for image and video files."""


    def __init__(self, scanner, moderator, notifier, batch_size=10, batch_timeout=60,
                 immich=None, review_store=None, dashboard_url=None):
        """
        Initialize the file handler.

        Args:
            scanner: Scanner instance for tracking processed files
            moderator: Moderator instance for detection and redaction
            notifier: Notifier instance for sending alerts
            batch_size: Number of detections before sending notification batch
            batch_timeout: Seconds to wait before sending incomplete batch (0 to disable)
            immich: Optional ImmichClient for asset and owner lookup
            review_store: Optional ReviewStore for the moderation dashboard
            dashboard_url: Optional dashboard base URL used in review links
        """
        self.scanner = scanner
        self.moderator = moderator
        self.batch_manager = BatchManager(notifier, batch_size, batch_timeout)
        self.supported_extensions = moderator.image_extensions | moderator.video_extensions
        self.immich = immich
        self.review_store = review_store
        self.dashboard_url = dashboard_url

    def on_created(self, event):
        """Called when a file or directory is created."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Check if it's a supported media file
        if file_path.suffix.lower() not in self.supported_extensions:
            return

        # Check if file still exists (may have been moved/deleted)
        if not file_path.exists():
            return

        try:
            # Check if already processed
            if not self.scanner.is_new_or_modified(str(file_path)):
                return
        except FileNotFoundError:
            # File was deleted/moved between detection and check
            return

        print(f"\nNew file detected: {file_path.name}")
        self._process_file(file_path)

    def _process_file(self, file_path):
        """Process a single file for explicit content."""
        try:
            batch = []
            process_media_file(
                file_path, self.moderator, self.scanner, batch,
                self.immich, self.review_store, self.dashboard_url
            )

            for item in batch:
                self.batch_manager.add(item)

        except Exception as e:
            print(f"Error processing {file_path}: {e}")


class MediaWatcher:
    """Watches a directory for new media files and processes them."""

    def __init__(self, directory, scanner, moderator, notifier, batch_size=10, batch_timeout=60,
                 immich=None, review_store=None, dashboard_url=None):
        """
        Initialize the watcher.

        Args:
            directory: Directory path to watch
            scanner: Scanner instance for tracking processed files
            moderator: Moderator instance for detection and redaction
            notifier: Notifier instance for sending alerts
            batch_size: Number of detections before sending notification batch
            batch_timeout: Seconds to wait before sending incomplete batch (0 to disable)
            immich: Optional ImmichClient for asset and owner lookup
            review_store: Optional ReviewStore for the moderation dashboard
            dashboard_url: Optional dashboard base URL used in review links
        """
        self.directory = Path(directory)
        self.event_handler = MediaFileHandler(
            scanner, moderator, notifier, batch_size, batch_timeout,
            immich, review_store, dashboard_url
        )
        self.observer = Observer()

    def start(self):
        """Start watching the directory."""
        self.observer.schedule(self.event_handler, str(self.directory), recursive=True)
        self.observer.start()
        print(f"\nWatching directory: {self.directory}")
        print("Press Ctrl+C to stop...")

    def stop(self):
        """Stop watching and clean up."""
        print("\nStopping watcher...")
        self.observer.stop()
        self.observer.join()

        # Send any remaining batch items
        self.event_handler.batch_manager.flush()
        print("Watcher stopped.")

    def run(self):
        """Run the watcher indefinitely until interrupted."""
        self.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
