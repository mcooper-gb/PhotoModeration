"""HTML email template generator for moderation alerts."""


class EmailTemplate:
    """Generate HTML email templates for moderation notifications."""

    @staticmethod
    def get_css_styles():
        """Return CSS styles for the email template."""
        return """
            body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
            h1 { color: #d32f2f; }
            .file-entry {
                border: 1px solid #ddd;
                padding: 20px;
                margin-bottom: 30px;
                background-color: #f9f9f9;
                border-radius: 5px;
            }
            .file-header {
                font-size: 18px;
                font-weight: bold;
                color: #d32f2f;
                margin-bottom: 10px;
            }
            .info-label {
                font-weight: bold;
                color: #555;
            }
            .detection-label {
                background-color: #fff3cd;
                padding: 2px 6px;
                border-radius: 3px;
                margin-right: 5px;
                margin-bottom: 5px;
                display: inline-block;
            }
            .confidence-score {
                font-size: 0.85em;
                color: #666;
                font-weight: normal;
            }
            .censored-image {
                max-width: 800px;
                margin-top: 15px;
                border: 2px solid #ddd;
                border-radius: 5px;
            }
            .separator {
                border-top: 2px solid #ddd;
                margin: 20px 0;
            }
            a { color: #1976d2; text-decoration: none; }
            a:hover { text-decoration: underline; }
        """

    @staticmethod
    def generate_html(results):
        """
        Generate HTML email content from detection results.

        Args:
            results: List of detection result dictionaries containing:
                - original_path: Path to original file
                - censored_path: Path to censored file
                - detections: Detection data
                - exif_data: EXIF metadata (optional)

        Returns:
            str: Complete HTML email content
        """
        html = f"""
        <html>
        <head>
            <style>
                {EmailTemplate.get_css_styles()}
            </style>
        </head>
        <body>
            <h1>🚨 Photo Moderation Alert</h1>
            <p>The following explicit files were detected and censored:</p>
        """

        for idx, res in enumerate(results, 1):
            html += EmailTemplate._generate_file_entry(idx, res)

        html += """
        </body>
        </html>
        """

        return html

    @staticmethod
    def _generate_file_entry(idx, res):
        """Generate HTML for a single file entry."""
        html = f'<div class="file-entry">'
        html += f'<div class="file-header">FILE #{idx}</div>'
        html += f'<p><span class="info-label">Path:</span> {res["original_path"]}</p>'

        # Add detection labels
        html += EmailTemplate._generate_detection_labels(res.get('detections', []))

        # Add EXIF data
        html += EmailTemplate._generate_exif_data(res.get('exif_data'))

        # Add inline image
        censored_path = res.get('censored_path')
        if censored_path and censored_path.exists():
            image_cid = f"image{idx}"
            html += f'<div><img src="cid:{image_cid}" class="censored-image" alt="Censored image {idx}"></div>'

        html += '</div>'
        return html

    @staticmethod
    def _generate_detection_labels(detections):
        """Generate HTML for detection labels with confidence scores."""
        # Collect detections with their scores
        label_scores = {}

        if isinstance(detections, dict):
            # Handle video detections (dict of frame_num: detections)
            for frame_detections in detections.values():
                if isinstance(frame_detections, list):
                    for det in frame_detections:
                        label = det.get('class', 'Unknown')
                        score = det.get('score', 0)
                        # Keep the highest score for each label
                        if label not in label_scores or score > label_scores[label]:
                            label_scores[label] = score
        else:
            # Handle image detections (list)
            for det in detections:
                label = det.get('class', 'Unknown')
                score = det.get('score', 0)
                # Keep the highest score for each label
                if label not in label_scores or score > label_scores[label]:
                    label_scores[label] = score

        html = f'<p><span class="info-label">Detections:</span><br>'
        for label in sorted(label_scores.keys()):
            score = label_scores[label]
            score_percent = int(score * 100)
            html += f'<span class="detection-label">{label} <span class="confidence-score">({score_percent}%)</span></span>'
        html += '</p>'

        return html

    @staticmethod
    def _generate_exif_data(exif_data):
        """Generate HTML for EXIF metadata."""
        if not exif_data:
            return '<p><span class="info-label">EXIF Data:</span> Not available</p>'

        html = ''
        if 'date_taken' in exif_data:
            html += f'<p><span class="info-label">Date Taken:</span> {exif_data["date_taken"]}</p>'
        if 'location' in exif_data:
            html += f'<p><span class="info-label">Location:</span> {exif_data["location"]}</p>'
            html += f'<p><span class="info-label">Google Maps:</span> <a href="{exif_data["google_maps_link"]}" target="_blank">View on Map</a></p>'

        return html
