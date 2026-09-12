"""Batch manager for handling notification batching with timeout support."""
import threading
from src.utils import cleanup_censored_files


class BatchManager:
    """Manages batching of notifications with size and timeout constraints."""

    def __init__(self, notifier, batch_size=10, batch_timeout=60):
        """
        Initialize the batch manager.

        Args:
            notifier: Notifier instance for sending alerts
            batch_size: Number of items before sending notification batch
            batch_timeout: Seconds to wait before sending incomplete batch (0 to disable)
        """
        self.notifier = notifier
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.batch = []
        self.batch_timer = None
        self.lock = threading.Lock()

    def add(self, item):
        """
        Add an item to the batch and send if batch is full.

        Args:
            item: Dictionary with batch item data (from create_batch_item)
        """
        send_now = False

        with self.lock:
            self.batch.append(item)

            self._cancel_timer()

            if len(self.batch) >= self.batch_size:
                send_now = True
            elif self.batch_timeout > 0:
                self.batch_timer = threading.Timer(self.batch_timeout, self._on_timeout)
                self.batch_timer.start()

        # Send batch outside the lock to avoid deadlock
        if send_now:
            self.send()

    def send(self):
        """Send the current batch and clean up."""
        with self.lock:
            self._cancel_timer()

            if not self.batch:
                return

            batch_to_send = self.batch
            self.batch = []

        print(f"\nSending batch of {len(batch_to_send)} notifications...")

        if not self.notifier.send_notification(batch_to_send):
            print("  Notification failed; the detections remain in the review queue")

        # Cleaned up either way: there is no retry, and the dashboard holds its
        # own copy, so keeping these would leave explicit images on disk with
        # no reader.
        cleanup_censored_files(batch_to_send)

    def flush(self):
        """Send any remaining items in the batch."""
        with self.lock:
            self._cancel_timer()

            if not self.batch:
                return

            batch_size = len(self.batch)

        print(f"\nFlushing remaining batch of {batch_size} notifications...")
        self.send()

    def _on_timeout(self):
        """Called by timer to send batch after timeout."""
        print(f"\nBatch timeout reached, sending notification(s)...")
        self.send()

    def _cancel_timer(self):
        """Cancel the current timer if active."""
        if self.batch_timer:
            self.batch_timer.cancel()
            self.batch_timer = None
