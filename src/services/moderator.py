import hashlib
import tempfile
from pathlib import Path

import cv2
from nudenet import NudeDetector

from src.utils.redaction import explicit_boxes, redact_frame


class Moderator:

    def __init__(self, explicit_labels, image_extensions, video_extensions, censored_dir,
                 confidence_threshold=0.6, redaction_mode='blur', redaction_strength=60,
                 redaction_padding=8):
        self.detector = NudeDetector()
        self.explicit_labels = explicit_labels
        self.image_extensions = image_extensions
        self.video_extensions = video_extensions
        self.censored_dir = Path(censored_dir)
        self.censored_dir.mkdir(parents=True, exist_ok=True)
        self.confidence_threshold = confidence_threshold
        self.redaction_mode = redaction_mode
        self.redaction_strength = redaction_strength
        self.redaction_padding = redaction_padding

    def is_video(self, file_path):
        return Path(file_path).suffix.lower() in self.video_extensions

    def is_explicit(self, detections):
        """Check if detections contain explicit content above confidence threshold."""
        if isinstance(detections, dict):
            detections = [det for frame in detections.values()
                          if isinstance(frame, list) for det in frame]

        return any(
            det.get('class') in self.explicit_labels and
            det.get('score', 0) >= self.confidence_threshold
            for det in detections
        )

    def detect(self, file_path):
        """Detect explicit content in image or video."""
        if self.is_video(file_path):
            return self._detect_video(file_path)
        return self.detector.detect(str(file_path))

    def _detect_video(self, video_path):
        """Detect explicit content in video with optimizations."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return {}

        original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 1.0

        # Frames are downscaled once on read and reused for both the background
        # subtractor and the detector. Asking the decoder to scale is not an option:
        # H.264 and HEVC have no reduced-resolution decode path, and
        # CAP_PROP_FRAME_WIDTH applies to capture devices rather than files.
        target_height = 480

        back_sub = cv2.createBackgroundSubtractorMOG2(detectShadows=False)

        frame_interval = max(1, int(fps * 2))  # 2 seconds between samples
        frame_count = 0
        detection_count = 0
        max_detections = 5
        detections = {}

        in_explicit_scene = False
        scene_change_threshold = 0.3  # 30% of frame pixels changed

        print(f"\n=== Processing video: {Path(video_path).name} ===")
        print(f"Resolution: {original_width}x{original_height}, FPS: {fps:.2f}")
        print(f"Sampling every {frame_interval} frames (~2 seconds)")

        while cap.isOpened() and detection_count < max_detections:
            ret, frame = cap.read()
            if not ret:
                break

            # Downscale before the subtractor: this runs on every frame, and its
            # cost scales with the pixel count.
            frame_for_detection = self._downscale(frame, target_height)
            detect_height, detect_width = frame_for_detection.shape[:2]

            fg_mask = back_sub.apply(frame_for_detection)
            change_ratio = cv2.countNonZero(fg_mask) / (detect_width * detect_height)

            # Wait for the picture to change, so one explicit scene is not
            # reported as several detections.
            if in_explicit_scene:
                if change_ratio > scene_change_threshold:
                    print(f"  Scene change detected at frame {frame_count} ({change_ratio:.2%} change)")
                    in_explicit_scene = False
                frame_count += 1
                continue

            if frame_count % frame_interval == 0:
                timestamp = frame_count / fps

                # NudeDetector reads from a path, not an array.
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                    tmp_path = tmp.name
                    cv2.imwrite(tmp_path, frame_for_detection)

                try:
                    frame_detections = self.detector.detect(tmp_path)

                    has_explicit = any(
                        det.get('class') in self.explicit_labels and
                        det.get('score', 0) >= self.confidence_threshold
                        for det in frame_detections
                    )

                    if has_explicit:
                        detection_count += 1
                        # _censor_video re-reads frames at full resolution, so the
                        # boxes are mapped back off the frame that was decoded.
                        frame_height, frame_width = frame.shape[:2]
                        detections[frame_count] = self._rescale_detections(
                            frame_detections,
                            frame_width / detect_width if detect_width else 1.0,
                            frame_height / detect_height if detect_height else 1.0
                        )
                        print(f"  Detection {detection_count}/5 at frame {frame_count} (t={timestamp:.1f}s)")
                        in_explicit_scene = True
                finally:
                    Path(tmp_path).unlink()

            frame_count += 1

        cap.release()
        print(f"Video processing complete: {detection_count} explicit frames found")
        return detections

    @staticmethod
    def _downscale(frame, target_height):
        """Shrink a frame to target_height, preserving aspect ratio."""
        height, width = frame.shape[:2]
        if height <= target_height:
            return frame

        scale = target_height / height
        return cv2.resize(frame, (max(1, int(width * scale)), target_height),
                          interpolation=cv2.INTER_AREA)

    @staticmethod
    def _rescale_detections(detections, x_scale, y_scale):
        """Scale detection boxes back to the original frame dimensions."""
        if x_scale == 1.0 and y_scale == 1.0:
            return detections

        rescaled = []
        for det in detections:
            box = det.get('box')
            if box and len(box) >= 4:
                det = dict(det)
                det['box'] = [
                    box[0] * x_scale,
                    box[1] * y_scale,
                    box[2] * x_scale,
                    box[3] * y_scale,
                ]
            rescaled.append(det)

        return rescaled

    def censor(self, file_path, detections=None):
        """
        Redact explicit content by blurring (or pixelating) the detected regions.

        Args:
            file_path: Path to the media file
            detections: Detection data from detect()

        Returns:
            Path for images, or a list of frame dicts for videos, or None
        """
        if self.is_video(file_path):
            return self._censor_video(file_path, detections)

        if detections is None:
            detections = self.detect(file_path)

        image = cv2.imread(str(file_path))
        if image is None:
            print(f"  Unable to read image for redaction: {file_path}")
            return None

        boxes = explicit_boxes(detections, self.explicit_labels, self.confidence_threshold)
        if not boxes:
            return None

        print(f"\n=== Redacting {Path(file_path).name} ({self.redaction_mode}, {len(boxes)} region(s)) ===")
        redact_frame(image, boxes, self.redaction_mode, self.redaction_strength, self.redaction_padding)

        output_path = self.censored_dir / self._output_name(file_path)
        if not cv2.imwrite(str(output_path), image):
            print(f"  Failed to write redacted image: {output_path}")
            return None

        return output_path

    def _censor_video(self, video_path, detections):
        """
        Redact detected frames in a video and save them as individual images.

        Returns:
            list[dict]: Entries with 'path', 'frame_number' and 'timestamp'
        """
        if not detections:
            return []

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 1.0
        censored_frames = []

        print(f"\n=== Redacting {len(detections)} frames from {Path(video_path).name} ===")

        for frame_num in sorted(detections.keys()):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()

            if not ret:
                continue

            timestamp = frame_num / fps
            boxes = explicit_boxes(detections[frame_num], self.explicit_labels, self.confidence_threshold)
            if not boxes:
                continue

            redact_frame(frame, boxes, self.redaction_mode, self.redaction_strength, self.redaction_padding)

            output_path = self.censored_dir / self._output_name(video_path, frame_num)
            if not cv2.imwrite(str(output_path), frame):
                print(f"  Failed to write redacted frame {frame_num}")
                continue

            censored_frames.append({
                'path': output_path,
                'frame_number': frame_num,
                'timestamp': timestamp,
            })
            print(f"  Redacted frame {frame_num} (t={timestamp:.1f}s) -> {output_path.name}")

        cap.release()
        print(f"Redacted {len(censored_frames)} frames")
        return censored_frames

    @staticmethod
    def extract_frame(video_path, frame_number):
        """
        Read a single frame from a video.

        Args:
            video_path: Path to the video file
            frame_number: Zero-based frame index

        Returns:
            OpenCV image array, or None if the frame could not be read
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None

        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(frame_number)))
            ret, frame = cap.read()
            return frame if ret else None
        finally:
            cap.release()

    @staticmethod
    def _output_name(source_path, frame_number=None):
        """Build a collision-free output filename for a redacted preview."""
        source_path = Path(source_path)
        digest = hashlib.sha1(str(source_path).encode('utf-8')).hexdigest()[:8]

        if frame_number is None:
            return f"redacted_{source_path.stem}_{digest}.jpg"
        return f"redacted_{source_path.stem}_{digest}_f{frame_number}.jpg"
