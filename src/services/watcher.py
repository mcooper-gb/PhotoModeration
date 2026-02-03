import time
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class MediaFileHandler(FileSystemEventHandler):
    """Handles file system events for image and video files."""

    SUPPORTED_EXTENSIONS = {
        # Images
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff',
        # Videos
        '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'
    }

    def __init__(self, scanner, moderator, notifier, batch_size=10, batch_timeout=60):
        """
        Initialize the file handler.

        Args:
            scanner: Scanner instance for tracking processed files
            moderator: Moderator instance for detection and censoring
            notifier: Notifier instance for sending alerts
            batch_size: Number of detections before sending notification batch
            batch_timeout: Seconds to wait before sending incomplete batch (0 to disable)
        """
        self.scanner = scanner
        self.moderator = moderator
        self.notifier = notifier
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.batch = []
        self.batch_timer = None
        self.timer_lock = threading.Lock()

    def on_created(self, event):
        """Called when a file or directory is created."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Check if it's a supported media file
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
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
            # Run detection
            detections = self.moderator.detect(file_path)

            if self.moderator.is_explicit(detections):
                print(f"Explicit content detected in {file_path}")

                # Censor the content
                censored_result = self.moderator.censor(file_path, detections)

                if censored_result:
                    # Handle different return types (Path for images, list for videos)
                    if isinstance(censored_result, list):
                        # Video returns list of censored frame paths
                        for censored_path in censored_result:
                            self._add_to_batch(file_path, censored_path, detections)
                    else:
                        # Image returns single Path
                        self._add_to_batch(file_path, censored_result, detections)

            # Mark as scanned regardless of result
            self.scanner.mark_as_scanned(str(file_path))

        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    def _add_to_batch(self, original_path, censored_path, detections=None):
        """Add detection to batch and send if batch is full."""
        relative_path = original_path.name

        with self.timer_lock:
            self.batch.append({
                'original_path': str(original_path),
                'censored_path': censored_path,
                'relative_path': relative_path,
                'detections': detections or []
            })

            # Cancel existing timer if any
            if self.batch_timer:
                self.batch_timer.cancel()
                self.batch_timer = None

            if len(self.batch) >= self.batch_size:
                self._send_batch()
            elif self.batch_timeout > 0:
                # Start timer for incomplete batch
                self.batch_timer = threading.Timer(self.batch_timeout, self._send_batch_on_timeout)
                self.batch_timer.start()

    def _send_batch_on_timeout(self):
        """Called by timer to send batch after timeout."""
        with self.timer_lock:
            if self.batch:
                print(f"\nBatch timeout reached, sending {len(self.batch)} notification(s)...")
                self._send_batch()

    def _send_batch(self):
        """Send notification batch and clean up censored files."""
        # Cancel timer if active (may be called directly when batch is full)
        if self.batch_timer:
            self.batch_timer.cancel()
            self.batch_timer = None

        if not self.batch:
            return

        print(f"\nSending batch of {len(self.batch)} notifications...")

        if self.notifier.send_notification(self.batch):
            # Clean up censored files after successful notification
            for item in self.batch:
                censored_path = item['censored_path']
                if isinstance(censored_path, Path) and censored_path.exists():
                    censored_path.unlink()

        self.batch = []

    def flush_batch(self):
        """Send any remaining items in the batch."""
        with self.timer_lock:
            # Cancel timer
            if self.batch_timer:
                self.batch_timer.cancel()
                self.batch_timer = None

            if self.batch:
                print(f"\nFlushing remaining batch of {len(self.batch)} notifications...")
                self._send_batch()


class MediaWatcher:
    """Watches a directory for new media files and processes them."""

    def __init__(self, directory, scanner, moderator, notifier, batch_size=10, batch_timeout=60):
        """
        Initialize the watcher.

        Args:
            directory: Directory path to watch
            scanner: Scanner instance for tracking processed files
            moderator: Moderator instance for detection and censoring
            notifier: Notifier instance for sending alerts
            batch_size: Number of detections before sending notification batch
            batch_timeout: Seconds to wait before sending incomplete batch (0 to disable)
        """
        self.directory = Path(directory)
        self.event_handler = MediaFileHandler(scanner, moderator, notifier, batch_size, batch_timeout)
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
        self.event_handler.flush_batch()
        print("Watcher stopped.")

    def run(self):
        """Run the watcher indefinitely until interrupted."""
        self.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
