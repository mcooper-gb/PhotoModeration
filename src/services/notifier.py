"""Email notification service for moderation alerts."""
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.templates.email_template import EmailTemplate
from src.utils.exif_extractor import ExifExtractor


class Notifier:
    """Handle email notifications for detected explicit content."""

    def __init__(self, smtp_server, smtp_port, smtp_user, smtp_pass, recipient):
        """
        Initialize the notifier with SMTP configuration.

        Args:
            smtp_server: SMTP server address
            smtp_port: SMTP server port
            smtp_user: SMTP username
            smtp_pass: SMTP password
            recipient: Email address to send notifications to
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.recipient = recipient
        self.exif_extractor = ExifExtractor()

    def send_notification(self, results):
        """
        Send email notification with detection results.

        Args:
            results: List of dicts containing:
                - original_path: Path to original file
                - censored_path: Path to censored file
                - relative_path: Relative filename
                - detections: Detection data

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
        html_content = EmailTemplate.generate_html(enriched_results)
        msg.attach(MIMEText(html_content, 'html'))

        # Attach images with Content-ID for inline display
        for idx, res in enumerate(enriched_results, 1):
            censored_path = res['censored_path']
            if censored_path.exists():
                with open(censored_path, 'rb') as f:
                    img_data = f.read()
                    image = MIMEImage(img_data)
                    image.add_header('Content-ID', f'<image{idx}>')
                    image.add_header('Content-Disposition', 'inline', filename=censored_path.name)
                    msg.attach(image)

        # Send email
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False
