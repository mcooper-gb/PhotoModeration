import cv2
import tempfile
from pathlib import Path
from nudenet import NudeDetector

class Moderator:
    EXPLICIT_LABELS = {
        'FEMALE_BREAST_EXPOSED',
        'FEMALE_GENITALIA_EXPOSED',
        'MALE_GENITALIA_EXPOSED',
        'BUTTOCKS_EXPOSED',
        'ANUS_EXPOSED',
        'MALE_BREAST_EXPOSED',
    }

    VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv'}

    def __init__(self, censored_dir):
        self.detector = NudeDetector()
        self.censored_dir = Path(censored_dir)
        self.censored_dir.mkdir(exist_ok=True)

    def is_video(self, file_path):
        return Path(file_path).suffix.lower() in self.VIDEO_EXTENSIONS

    def is_explicit(self, detections):
        """Check if detections contain explicit content."""
        if isinstance(detections, dict):
            detections = [det for frame in detections.values()
                         if isinstance(frame, list) for det in frame]

        return any(det.get('class') in self.EXPLICIT_LABELS for det in detections)

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
        fps = cap.get(cv2.CAP_PROP_FPS)

        # Calculate 480p dimensions
        target_height = 480
        if original_height > target_height:
            scale_factor = target_height / original_height
            target_width = int(original_width * scale_factor)
        else:
            target_width = original_width
            target_height = original_height
            scale_factor = 1.0

        # Try codec-level scaling (option 3)
        use_manual_scaling = False
        if scale_factor < 1.0:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_height)

            # Check if codec actually applied the scaling
            actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if actual_width == target_width and actual_height == target_height:
                print(f"Codec-level scaling successful: {original_width}x{original_height} -> {target_width}x{target_height}")
                width, height = target_width, target_height
            else:
                print(f"Codec doesn't support scaling, will use manual downscaling")
                use_manual_scaling = True
                width, height = original_width, original_height
        else:
            width, height = original_width, original_height

        # Background subtraction for scene detection
        back_sub = cv2.createBackgroundSubtractorMOG2(detectShadows=False)

        frame_interval = max(1, int(fps * 2))  # 2 seconds between samples
        frame_count = 0
        detection_count = 0
        max_detections = 5
        detections = {}

        in_explicit_scene = False
        scene_change_threshold = 0.3  # 30% of frame pixels changed

        print(f"\n=== Processing video: {Path(video_path).name} ===")
        print(f"Resolution: {width}x{height}, FPS: {fps:.2f}")
        print(f"Sampling every {frame_interval} frames (~2 seconds)")

        while cap.isOpened() and detection_count < max_detections:
            ret, frame = cap.read()
            if not ret:
                break

            # Apply background subtraction to detect scene changes
            fg_mask = back_sub.apply(frame)
            change_ratio = cv2.countNonZero(fg_mask) / (width * height)

            # If we're in an explicit scene, wait for scene change
            if in_explicit_scene:
                if change_ratio > scene_change_threshold:
                    print(f"  Scene change detected at frame {frame_count} ({change_ratio:.2%} change)")
                    in_explicit_scene = False
                frame_count += 1
                continue

            # Only process frames at the sampling interval
            if frame_count % frame_interval == 0:
                timestamp = frame_count / fps

                # Downscale for detection if needed (option 2 fallback)
                if use_manual_scaling:
                    frame_for_detection = cv2.resize(frame, (target_width, target_height))
                else:
                    frame_for_detection = frame

                # Save frame temporarily and run detection
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                    tmp_path = tmp.name
                    cv2.imwrite(tmp_path, frame_for_detection)

                try:
                    frame_detections = self.detector.detect(tmp_path)

                    # Check if any explicit content detected
                    has_explicit = any(det.get('class') in self.EXPLICIT_LABELS
                                     for det in frame_detections)

                    if has_explicit:
                        detection_count += 1
                        detections[frame_count] = frame_detections
                        print(f"  Detection {detection_count}/5 at frame {frame_count} (t={timestamp:.1f}s)")
                        in_explicit_scene = True
                finally:
                    Path(tmp_path).unlink()

            frame_count += 1

        cap.release()
        print(f"Video processing complete: {detection_count} explicit frames found")
        return detections

    def censor(self, file_path, detections=None):
        """Censor explicit content using NudeNet's built-in censoring."""
        if self.is_video(file_path):
            return self._censor_video(file_path, detections)

        output_path = self.censored_dir / f"censored_{Path(file_path).name}"

        print(f"\n=== Censoring {Path(file_path).name} ===")
        censored_path = self.detector.censor(
            str(file_path),
            classes=list(self.EXPLICIT_LABELS),
            output_path=str(output_path)
        )

        return Path(censored_path) if censored_path else None

    def _censor_video(self, video_path, detections):
        """Censor detected frames in video and save as individual images."""
        if not detections:
            return []

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS)
        censored_frames = []

        print(f"\n=== Censoring {len(detections)} frames from {Path(video_path).name} ===")

        for frame_num in sorted(detections.keys()):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()

            if not ret:
                continue

            timestamp = frame_num / fps

            # Save frame temporarily
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp_path = tmp.name
                cv2.imwrite(tmp_path, frame)

            try:
                # Use NudeNet to censor the frame
                video_stem = Path(video_path).stem
                output_filename = f"censored_{video_stem}_t{timestamp:.2f}s_f{frame_num}.jpg"
                output_path = self.censored_dir / output_filename

                censored_path = self.detector.censor(
                    tmp_path,
                    classes=list(self.EXPLICIT_LABELS),
                    output_path=str(output_path)
                )

                if censored_path:
                    censored_frames.append(Path(censored_path))
                    print(f"  Censored frame {frame_num} (t={timestamp:.1f}s) -> {output_filename}")
            finally:
                Path(tmp_path).unlink()

        cap.release()
        print(f"Censored {len(censored_frames)} frames")
        return censored_frames

    def _censor_video(self, video_path, detections):
        """Censor detected frames in video and save as individual images."""
        if not detections:
            return []

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS)
        censored_frames = []

        print(f"\n=== Censoring {len(detections)} frames from {Path(video_path).name} ===")

        for frame_num in sorted(detections.keys()):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()

            if not ret:
                continue

            timestamp = frame_num / fps

            # Save frame temporarily
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp_path = tmp.name
                cv2.imwrite(tmp_path, frame)

            try:
                # Use NudeNet to censor the frame
                video_stem = Path(video_path).stem
                output_filename = f"censored_{video_stem}_t{timestamp:.2f}s_f{frame_num}.jpg"
                output_path = self.censored_dir / output_filename

                censored_path = self.detector.censor(
                    tmp_path,
                    classes=list(self.EXPLICIT_LABELS),
                    output_path=str(output_path)
                )

                if censored_path:
                    censored_frames.append(Path(censored_path))
                    print(f"  Censored frame {frame_num} (t={timestamp:.1f}s) -> {output_filename}")
            finally:
                Path(tmp_path).unlink()

        cap.release()
        print(f"Censored {len(censored_frames)} frames")
        return censored_frames
