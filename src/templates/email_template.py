"""HTML email template generator for moderation alerts."""
from html import escape
from pathlib import Path


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
            .actions {
                margin-top: 15px;
            }
            .action-button {
                display: inline-block;
                padding: 8px 14px;
                margin-right: 10px;
                border-radius: 4px;
                background-color: #1976d2;
                color: #ffffff !important;
                font-weight: bold;
            }
            .action-secondary {
                background-color: #5f6368;
            }
            .warning {
                font-size: 0.85em;
                color: #b26a00;
            }
            .separator {
                border-top: 2px solid #ddd;
                margin: 20px 0;
            }
            a { color: #1976d2; text-decoration: none; }
            a:hover { text-decoration: underline; }
        """

    @staticmethod
    def generate_html(results, dashboard_url=None):
        """
        Generate HTML email content from detection results.

        Args:
            results: List of detection result dictionaries containing:
                - original_path: Path to original file
                - censored_path: Path to redacted preview
                - detections: Detection data
                - exif_data: EXIF metadata (optional)
                - owner_name / owner_email: Immich uploader (optional)
                - immich_link: Link to the asset in Immich (optional)
                - review_link: Link to the dashboard review page (optional)
            dashboard_url: Base URL of the moderation dashboard (optional)

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
            <p>The following explicit files were detected and redacted:</p>
        """

        if dashboard_url:
            html += (
                f'<p><a class="action-button" href="{escape(dashboard_url, quote=True)}">'
                f'Open moderation dashboard</a></p>'
            )

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
        html += f'<p><span class="info-label">Path:</span> {escape(str(res["original_path"]))}</p>'

        # Add the Immich uploader, when the asset could be identified
        html += EmailTemplate._generate_owner_info(res)

        # Add frame details for video detections
        if res.get('frame_number') is not None:
            timestamp = res.get('frame_timestamp')
            position = f" (t={timestamp:.1f}s)" if isinstance(timestamp, (int, float)) else ''
            html += f'<p><span class="info-label">Frame:</span> {res["frame_number"]}{position}</p>'

        # Add detection labels
        html += EmailTemplate._generate_detection_labels(res.get('detections', []))

        # Add EXIF data
        html += EmailTemplate._generate_exif_data(res.get('exif_data'))

        # Add inline redacted image
        censored_path = res.get('censored_path')
        if censored_path and Path(censored_path).exists():
            image_cid = f"image{idx}"
            html += f'<div><img src="cid:{image_cid}" class="censored-image" alt="Redacted image {idx}"></div>'

        html += EmailTemplate._generate_actions(res)
        html += '</div>'
        return html

    @staticmethod
    def _generate_owner_info(res):
        """Generate HTML for the Immich uploader details."""
        name = res.get('owner_name')
        email = res.get('owner_email')

        if not name and not email:
            if res.get('immich_asset_id'):
                return '<p><span class="info-label">Uploaded by:</span> Unknown Immich user</p>'
            return '<p><span class="info-label">Uploaded by:</span> Not matched to an Immich asset</p>'

        display = escape(name) if name else ''
        if email:
            contact = f'<a href="mailto:{escape(email, quote=True)}">{escape(email)}</a>'
            display = f'{display} ({contact})' if display else contact

        return f'<p><span class="info-label">Uploaded by:</span> {display}</p>'

    @staticmethod
    def _generate_actions(res):
        """Generate the review and Immich links for a detection."""
        review_link = res.get('review_link')
        immich_link = res.get('immich_link')

        if not review_link and not immich_link:
            return ''

        html = '<div class="actions">'
        if review_link:
            html += (
                f'<a class="action-button" href="{escape(review_link, quote=True)}">'
                f'Review (redacted)</a>'
            )
        if immich_link:
            html += (
                f'<a class="action-button action-secondary" href="{escape(immich_link, quote=True)}">'
                f'Open in Immich</a>'
            )
        html += '</div>'

        if immich_link:
            html += '<p class="warning">The Immich link shows the original, unredacted asset.</p>'

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
            html += f'<span class="detection-label">{escape(str(label))} <span class="confidence-score">({score_percent}%)</span></span>'
        html += '</p>'

        return html

    @staticmethod
    def _generate_exif_data(exif_data):
        """Generate HTML for EXIF metadata."""
        if not exif_data:
            return '<p><span class="info-label">EXIF Data:</span> Not available</p>'

        html = ''
        if 'date_taken' in exif_data:
            html += f'<p><span class="info-label">Date Taken:</span> {escape(str(exif_data["date_taken"]))}</p>'
        if 'location' in exif_data:
            html += f'<p><span class="info-label">Location:</span> {escape(str(exif_data["location"]))}</p>'
            html += f'<p><span class="info-label">Google Maps:</span> <a href="{escape(exif_data["google_maps_link"], quote=True)}" target="_blank">View on Map</a></p>'

        return html
