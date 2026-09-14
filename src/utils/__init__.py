"""Utility functions for the Photo Moderation Service."""
from pathlib import Path


def create_batch_item(original_path, censored_path, detections=None, context=None):
    """
    Create a batch item dictionary for notifications.

    Args:
        original_path: Path to the original file
        censored_path: Path to the redacted preview
        detections: List of detection results
        context: Extra fields (Immich owner/link, review id, frame details)

    Returns:
        Dictionary with batch item data
    """
    item = {
        'original_path': str(original_path),
        'censored_path': censored_path,
        'relative_path': Path(original_path).name,
        'detections': detections or []
    }
    item.update(context or {})
    return item


def cleanup_censored_files(batch):
    """
    Clean up redacted previews after successful notification.

    The copy retained in the review directory for the dashboard is separate
    and is not affected by this cleanup.

    Args:
        batch: List of batch items containing censored_path
    """
    for item in batch:
        censored_path = item['censored_path']
        if isinstance(censored_path, Path) and censored_path.exists():
            censored_path.unlink()


def add_censored_results_to_batch(original_path, censored_result, detections, batch, context=None):
    """
    Add redacted results to batch, handling both images (single Path) and videos
    (list of frame dictionaries).

    Args:
        original_path: Path to the original file
        censored_result: A Path (image) or list of frame dicts (video)
        detections: Detection results
        batch: List to append batch items to
        context: Shared context applied to every item (owner, links, ids)
    """
    context = dict(context or {})

    if isinstance(censored_result, list):
        for frame in censored_result:
            frame_context = dict(context)
            frame_context.update({
                'frame_number': frame.get('frame_number'),
                'frame_timestamp': frame.get('timestamp'),
            })
            batch.append(create_batch_item(original_path, frame.get('path'), detections, frame_context))
    else:
        batch.append(create_batch_item(original_path, censored_result, detections, context))


def build_review_link(dashboard_url, review_id):
    """Build the dashboard link for a review item."""
    if not dashboard_url or not review_id:
        return None
    return f"{dashboard_url.rstrip('/')}/review/{review_id}"


def process_media_file(file_path, moderator, scanner, batch, immich=None, review_store=None,
                       dashboard_url=None):
    """
    Process a single media file for explicit content.

    Args:
        file_path: Path to the file to process
        moderator: Moderator instance for detection and redaction
        scanner: Scanner instance to mark file as scanned
        batch: List to append detection results to
        immich: Optional Immich integration used to identify the asset and its owner
        review_store: Optional ReviewStore used to queue the detection for review
        dashboard_url: Optional dashboard base URL used to build review links
    """
    detections = moderator.detect(file_path)

    if moderator.is_explicit(detections):
        print(f"  Explicit content detected!")
        censored_result = moderator.censor(file_path, detections)

        if censored_result:
            media_type = 'video' if moderator.is_video(file_path) else 'image'
            immich_context = _resolve_immich_context(immich, file_path)
            context = {
                'media_type': media_type,
                'immich_asset_id': immich_context.get('asset_id'),
                'immich_link': immich_context.get('link'),
                'owner_name': immich_context.get('owner_name'),
                'owner_email': immich_context.get('owner_email'),
                'frame_number': None,
                'frame_timestamp': None,
            }

            add_censored_results_to_batch(file_path, censored_result, detections, batch, context)

            if review_store:
                _queue_for_review(
                    batch, file_path, detections, media_type,
                    immich_context, review_store, dashboard_url
                )

    scanner.mark_as_scanned(str(file_path))


def _resolve_immich_context(immich, file_path):
    """Look up the Immich asset and owner for a file, tolerating failures."""
    if not immich:
        return {}

    try:
        context = immich.resolve_asset(file_path)
    except Exception as e:
        print(f"  Immich lookup failed for {Path(file_path).name}: {e}")
        return {}

    if context.get('asset_id'):
        owner = context.get('owner_name') or context.get('owner_id') or 'unknown owner'
        print(f"  Immich asset {context['asset_id']} owned by {owner} ({context.get('resolved_by')})")
    else:
        print(f"  No Immich asset matched {Path(file_path).name}")

    return context


def _queue_for_review(batch, file_path, detections, media_type, immich_context, review_store,
                      dashboard_url):
    """Add the newly created batch items to the moderation review queue."""
    for item in batch:
        if item.get('review_id') or item['original_path'] != str(file_path):
            continue

        review_id = review_store.add(
            original_path=file_path,
            redacted_path=item.get('censored_path'),
            detections=detections,
            media_type=media_type,
            immich_context=immich_context,
            frame_number=item.get('frame_number'),
            frame_timestamp=item.get('frame_timestamp'),
        )

        if review_id:
            item['review_id'] = review_id
            item['review_link'] = build_review_link(dashboard_url, review_id)
