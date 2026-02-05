# Utilities module
"""Utility functions for the Photo Moderation Service."""
from pathlib import Path


def create_batch_item(original_path, censored_path, detections=None):
    """
    Create a batch item dictionary for notifications.

    Args:
        original_path: Path to the original file
        censored_path: Path to the censored file
        detections: List of detection results

    Returns:
        Dictionary with batch item data
    """
    return {
        'original_path': str(original_path),
        'censored_path': censored_path,
        'relative_path': Path(original_path).name,
        'detections': detections or []
    }


def cleanup_censored_files(batch):
    """
    Clean up censored files after successful notification.

    Args:
        batch: List of batch items containing censored_path
    """
    for item in batch:
        censored_path = item['censored_path']
        if isinstance(censored_path, Path) and censored_path.exists():
            censored_path.unlink()


def add_censored_results_to_batch(original_path, censored_result, detections, batch):
    """
    Add censored results to batch, handling both images (single Path) and videos (list of Paths).

    Args:
        original_path: Path to the original file
        censored_result: Either a Path (image) or list of Paths (video frames)
        detections: List of detection results
        batch: List to append batch items to
    """
    if isinstance(censored_result, list):
        # Video returns list of censored frame paths
        for censored_path in censored_result:
            batch.append(create_batch_item(original_path, censored_path, detections))
    else:
        # Image returns single Path
        batch.append(create_batch_item(original_path, censored_result, detections))

def process_media_file(file_path, moderator, scanner, batch):
    """
    Process a single media file for explicit content.

    Args:
        file_path: Path to the file to process
        moderator: Moderator instance for detection and censoring
        scanner: Scanner instance to mark file as scanned
        batch: List to append detection results to
    """
    detections = moderator.detect(file_path)

    if moderator.is_explicit(detections):
        print(f"  Explicit content detected!")
        censored_result = moderator.censor(file_path, detections)

        if censored_result:
            add_censored_results_to_batch(file_path, censored_result, detections, batch)

    scanner.mark_as_scanned(str(file_path))