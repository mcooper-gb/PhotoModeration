import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path

class Notifier:
    def __init__(self, smtp_server, smtp_port, smtp_user, smtp_pass, recipient):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.recipient = recipient

    def send_notification(self, results):
        """
        results: list of dicts {'original_path': Path, 'censored_path': Path, 'relative_path': str}
        """
        if not results:
            return

        msg = MIMEMultipart()
        msg['From'] = self.smtp_user
        msg['To'] = self.recipient
        msg['Subject'] = f"Photo Moderation Alert: {len(results)} files found"

        body = "The following explicit files were detected and censored:\n\n"
        for res in results:
            body += f"- {res['relative_path']}\n"
        
        msg.attach(MIMEText(body, 'plain'))

        for res in results:
            censored_path = res['censored_path']
            if censored_path.exists():
                with open(censored_path, 'rb') as f:
                    img_data = f.read()
                    image = MIMEImage(img_data, name=censored_path.name)
                    msg.attach(image)

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False
