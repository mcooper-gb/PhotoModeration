"""Redaction helpers for obscuring explicit regions in media frames."""
import cv2


def normalise_detections(detections):
    """
    Flatten detections into a single list.

    Args:
        detections: List of detections (image) or dict of frame_num -> list (video)

    Returns:
        list: Flat list of detection dictionaries
    """
    if isinstance(detections, dict):
        return [det for frame in detections.values()
                if isinstance(frame, list) for det in frame]
    return list(detections or [])


def explicit_boxes(detections, explicit_labels, confidence_threshold):
    """
    Extract the bounding boxes that should be redacted.

    Args:
        detections: Detection list for a single image/frame
        explicit_labels: Set of labels considered explicit
        confidence_threshold: Minimum score required

    Returns:
        list[tuple]: (x, y, width, height) boxes
    """
    boxes = []
    for det in normalise_detections(detections):
        if det.get('class') not in explicit_labels:
            continue
        if det.get('score', 0) < confidence_threshold:
            continue

        box = det.get('box')
        if not box or len(box) < 4:
            continue

        x, y, width, height = (int(round(value)) for value in box[:4])
        if width > 0 and height > 0:
            boxes.append((x, y, width, height))

    return boxes


def redact_frame(image, boxes, mode='blur', strength=60, padding=8):
    """
    Obscure the given regions of an image in place.

    Args:
        image: OpenCV BGR image array (modified in place)
        boxes: Iterable of (x, y, width, height) regions
        mode: 'blur', 'pixelate' or 'box'
        strength: Redaction intensity from 1 (light) to 100 (heavy)
        padding: Pixels to expand each region by before redacting

    Returns:
        The redacted image array
    """
    if image is None:
        return None

    frame_height, frame_width = image.shape[:2]
    strength = max(1, min(100, strength))

    for x, y, width, height in boxes:
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(frame_width, x + width + padding)
        y2 = min(frame_height, y + height + padding)

        if x2 <= x1 or y2 <= y1:
            continue

        region = image[y1:y2, x1:x2]

        if mode == 'box':
            image[y1:y2, x1:x2] = 0
        elif mode == 'pixelate':
            image[y1:y2, x1:x2] = _pixelate(region, strength)
        else:
            image[y1:y2, x1:x2] = _blur(region, strength)

    return image


def _blur(region, strength):
    """Apply a Gaussian blur scaled to the region size and strength."""
    height, width = region.shape[:2]

    # Kernel is a fraction of the shortest edge so small and large regions
    # end up equally unreadable. Must be odd and at least 3 pixels.
    kernel_size = max(3, int(min(height, width) * (strength / 100.0) * 0.6))
    if kernel_size % 2 == 0:
        kernel_size += 1

    sigma = max(1.0, kernel_size / 3.0)
    blurred = cv2.GaussianBlur(region, (kernel_size, kernel_size), sigma)

    # A second pass removes the ghosting that can survive a single blur of a
    # high-contrast region.
    if strength >= 50:
        blurred = cv2.GaussianBlur(blurred, (kernel_size, kernel_size), sigma)

    return blurred


def _pixelate(region, strength):
    """Downscale then upscale a region to produce a mosaic effect."""
    height, width = region.shape[:2]

    # Higher strength means fewer mosaic blocks.
    blocks = max(2, int(24 - (strength / 100.0) * 20))
    small_width = max(1, width // blocks)
    small_height = max(1, height // blocks)

    small = cv2.resize(region, (small_width, small_height), interpolation=cv2.INTER_LINEAR)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)
