import os

from config import Config
from moderator import Moderator
from scanner import Scanner


def test_detection():
    # Override configuration for testing
    # If running in Docker, we use /data as default. On Windows, we use the original hardcoded path.
    TEST_SCAN_DIR = os.getenv('TEST_SCAN_DIR',
                              r"C:\Users\mark_\Downloads\DETECTOR_AUTO_GENERATED_DATA\DETECTOR_AUTO_GENERATED_DATA")

    if not os.path.exists(TEST_SCAN_DIR):
        # Fallback for Docker if the hardcoded Windows path is still there but not found
        if os.path.exists('/data'):
            TEST_SCAN_DIR = '/data'
        else:
            print(f"Error: Test directory not found: {TEST_SCAN_DIR}")
            return

    print(f"--- TEST MODE: Detection only ---")
    print(f"Scanning directory: {TEST_SCAN_DIR}")
    print(f"Censored files will be saved to: {Config.CENSORED_DIR}")
    print(f"Emails will NOT be sent.\n")

    # Initialize components (skipping Notifier)
    # We use a temporary DB for testing to not interfere with production scanning
    TEST_DB = "test_scanned_files.db"
    scanner = Scanner(TEST_SCAN_DIR, TEST_DB)
    moderator = Moderator(Config.CENSORED_DIR)

    found_explicit = 0
    total_processed = 0

    try:
        for file_path in scanner.get_new_files():
            total_processed += 1
            print(f"[{total_processed}] Processing {file_path.name}...")
            try:
                detections = moderator.detect(file_path)
                if moderator.is_explicit(detections):
                    found_explicit += 1
                    print(f"  >>> EXPLICIT content detected!")
                    censored_path = moderator.censor(file_path, detections)
                    if censored_path:
                        print(f"  >>> Censored version saved: {censored_path}")
                else:
                    print(f"  Clean.")

                # We mark as scanned in the test DB
                scanner.mark_as_scanned(file_path)

            except Exception as e:
                print(f"  Error processing {file_path}: {e}")

    except KeyboardInterrupt:
        print("\nTest interrupted by user.")

    print(f"\n--- Test Summary ---")
    print(f"Total files scanned: {total_processed}")
    print(f"Explicit files found: {found_explicit}")
    print(f"Test database saved to: {TEST_DB}")
    print(f"Done.")


if __name__ == '__main__':
    test_detection()
