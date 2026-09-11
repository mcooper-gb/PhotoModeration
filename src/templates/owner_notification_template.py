"""Email template for notifying an uploader that their asset was removed."""
from html import escape


class OwnerNotificationTemplate:
    """Generate the message sent to the owner of a removed asset."""

    ACTION_TEXT = {
        'deleted': 'permanently deleted',
        'trashed': 'moved to your trash',
    }

    @staticmethod
    def _summary(item, action):
        """Build the shared wording for both the text and HTML bodies."""
        outcome = OwnerNotificationTemplate.ACTION_TEXT.get(action, 'removed')
        greeting = f"Hello {item['owner_name']}," if item.get('owner_name') else "Hello,"
        return greeting, outcome

    @staticmethod
    def generate_text(item, action='deleted', note=None):
        """
        Generate the plain text body.

        Args:
            item: Review item dict
            action: 'deleted' or 'trashed'
            note: Optional moderator message

        Returns:
            str: Plain text email body
        """
        greeting, outcome = OwnerNotificationTemplate._summary(item, action)

        lines = [
            greeting,
            "",
            "One of your uploads was reviewed by a moderator and flagged as explicit content.",
            f"The file has been {outcome}.",
            "",
            f"File: {item.get('file_name', 'unknown')}",
        ]

        if item.get('detected_at'):
            lines.append(f"Flagged: {item['detected_at']}")

        if action == 'trashed':
            lines += [
                "",
                "Trashed items stay recoverable in Immich until the trash is emptied.",
            ]

        if note:
            lines += ["", f"Moderator note: {note}"]

        lines += [
            "",
            "If you believe this was a mistake, reply to this email to contact the moderation team.",
        ]

        return "\n".join(lines)

    @staticmethod
    def generate_html(item, action='deleted', note=None):
        """
        Generate the HTML body.

        Args:
            item: Review item dict
            action: 'deleted' or 'trashed'
            note: Optional moderator message

        Returns:
            str: HTML email body
        """
        greeting, outcome = OwnerNotificationTemplate._summary(item, action)

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <p>{escape(greeting)}</p>
            <p>
                One of your uploads was reviewed by a moderator and flagged as explicit content.
                The file has been <strong>{outcome}</strong>.
            </p>
            <p><strong>File:</strong> {escape(str(item.get('file_name', 'unknown')))}</p>
        """

        if item.get('detected_at'):
            html += f'<p><strong>Flagged:</strong> {escape(str(item["detected_at"]))}</p>'

        if action == 'trashed':
            html += '<p>Trashed items stay recoverable in Immich until the trash is emptied.</p>'

        if note:
            html += f'<p><strong>Moderator note:</strong> {escape(str(note))}</p>'

        html += """
            <p>If you believe this was a mistake, reply to this email to contact the moderation team.</p>
        </body>
        </html>
        """

        return html
