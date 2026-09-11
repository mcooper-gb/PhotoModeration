"""Email notification service for moderation alerts."""
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from src.templates.email_template import EmailTemplate
from src.templates.owner_notification_template import OwnerNotificationTemplate
from src.utils.exif_extractor import ExifExtractor


class Notifier:
    """Handle email notifications for detected explicit content."""

    def __init__(self, smtp_server, smtp_port, smtp_user, smtp_pass, recipient, dashboard_url=None):
        """
        Initialize the notifier with SMTP configuration.

        Args:
            smtp_server: SMTP server address
            smtp_port: SMTP server port
            smtp_user: SMTP username
            smtp_pass: SMTP password
            recipient: Email address to send moderation alerts to
            dashboard_url: Base URL of the moderation dashboard, used in links
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.recipient = recipient
        self.dashboard_url = dashboard_url
        self.exif_extractor = ExifExtractor()

    def send_notification(self, results):
        """
        Send email notification with detection results.

        Args:
            results: List of dicts containing:
                - original_path: Path to original file
                - censored_path: Path to redacted preview
                - relative_path: Relative filename
                - detections: Detection data
                - owner_name / owner_email: Immich uploader, when known
                - immich_link: Link to the asset in Immich
                - review_link: Link to the dashboard review page

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        if not results:
            return False

        # Enrich results with EXIF data
        enriched_results = []
        for res in results:
            enriched_res = res.copy()
            enriched_res['exif_data'] = self.exif_extractor.extract_metadata(res['original_path'])
            enriched_results.append(enriched_res)

        # Create email message
        msg = MIMEMultipart('related')
        msg['From'] = self.smtp_user
        msg['To'] = self.recipient
        msg['Subject'] = f"Photo Moderation Alert: {len(results)} files found"

        # Generate HTML content
        html_content = EmailTemplate.generate_html(enriched_results, self.dashboard_url)
        msg.attach(MIMEText(html_content, 'html'))

        # Attach redacted previews with Content-ID for inline display. The
        # subtype is stated rather than guessed so a truncated preview cannot
        # take down the whole batch notification.
        for idx, res in enumerate(enriched_results, 1):
            censored_path = res['censored_path']
            if censored_path and Path(censored_path).exists():
                with open(censored_path, 'rb') as f:
                    image = MIMEImage(f.read(), _subtype='jpeg')
                    image.add_header('Content-ID', f'<image{idx}>')
                    image.add_header('Content-Disposition', 'inline', filename=Path(censored_path).name)
                    msg.attach(image)

        return self._send(msg)

    def send_owner_notification(self, item, action='deleted', note=None):
        """
        Tell the uploader that their asset was removed by a moderator.

        Args:
            item: Review item dict containing owner_email, file_name and detected_at
            action: What happened to the asset ('deleted' or 'trashed')
            note: Optional message from the moderator

        Returns:
            tuple[bool, str]: Success flag and a human readable detail message
        """
        recipient = item.get('owner_email')
        if not recipient:
            return False, "No email address is known for the asset owner"

        msg = MIMEMultipart('alternative')
        msg['From'] = self.smtp_user
        msg['To'] = recipient
        msg['Subject'] = "Your upload was removed by content moderation"

        msg.attach(MIMEText(OwnerNotificationTemplate.generate_text(item, action, note), 'plain'))
        msg.attach(MIMEText(OwnerNotificationTemplate.generate_html(item, action, note), 'html'))

        if self._send(msg):
            return True, f"Owner notified at {recipient}"
        return False, f"Failed to email the owner at {recipient}"

    def _send(self, msg):
        """
        Deliver a message over SMTP.

        Returns:
            bool: True if the message was accepted by the server
        """
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False
