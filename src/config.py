import os

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value, default=False):
    """Parse a truthy environment variable value."""
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


class Config:
    SCAN_DIR = os.getenv('SCAN_DIR', '.')
    EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
    SMTP_SERVER = os.getenv('SMTP_SERVER')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER')
    SMTP_PASS = os.getenv('SMTP_PASS')
    DB_PATH = os.getenv('DB_PATH', 'scanned_images.db')
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', 10))
    BATCH_TIMEOUT = int(os.getenv('BATCH_TIMEOUT', 60))
    CENSORED_DIR = os.getenv('CENSORED_DIR', 'censored_images')
    CONFIDENCE_THRESHOLD = float(os.getenv('CONFIDENCE_THRESHOLD', 0.6))
    EXPLICIT_LABELS = {
        'FEMALE_BREAST_EXPOSED',
        'FEMALE_GENITALIA_EXPOSED',
        'MALE_GENITALIA_EXPOSED',
        'BUTTOCKS_EXPOSED',
        'ANUS_EXPOSED',
    }
    VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv'}
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}

    # --- Redaction -------------------------------------------------------
    # blur (default), pixelate or box (the original black rectangle).
    REDACTION_MODE = os.getenv('REDACTION_MODE', 'blur').strip().lower()
    REDACTION_STRENGTH = int(os.getenv('REDACTION_STRENGTH', 60))
    REDACTION_PADDING = int(os.getenv('REDACTION_PADDING', 8))

    # --- Immich integration ----------------------------------------------
    # Reachable by the moderator's browser, unlike the internal hostname.
    IMMICH_EXTERNAL_URL = (os.getenv('IMMICH_EXTERNAL_URL') or '').rstrip('/')
    # Maps the locally mounted paths onto the paths Immich stores internally,
    # e.g. "/data/scan:upload/library" (comma separated for multiple mounts).
    IMMICH_PATH_MAP = os.getenv('IMMICH_PATH_MAP', '')

    # Immich database. This is the whole integration: Immich API keys only ever
    # cover the user that created them, so the API cannot moderate a shared
    # library at all.
    IMMICH_DB_URL = os.getenv('IMMICH_DB_URL')
    IMMICH_DB_HOST = os.getenv('IMMICH_DB_HOST')
    IMMICH_DB_PORT = int(os.getenv('IMMICH_DB_PORT', 5432))
    IMMICH_DB_NAME = os.getenv('IMMICH_DB_NAME', 'immich')
    IMMICH_DB_USER = os.getenv('IMMICH_DB_USER', 'postgres')
    IMMICH_DB_PASSWORD = os.getenv('IMMICH_DB_PASSWORD')
    IMMICH_DB_TIMEOUT = int(os.getenv('IMMICH_DB_TIMEOUT', 10))

    # trash (recoverable, default) or permanent.
    IMMICH_DELETE_MODE = os.getenv('IMMICH_DELETE_MODE', 'trash').strip().lower()
    # Pre-tick the "notify owner" checkbox in the dashboard.
    IMMICH_NOTIFY_OWNER_DEFAULT = _as_bool(os.getenv('IMMICH_NOTIFY_OWNER_DEFAULT'), False)

    # --- Moderation dashboard --------------------------------------------
    DASHBOARD_ENABLED = _as_bool(os.getenv('DASHBOARD_ENABLED'), True)
    DASHBOARD_HOST = os.getenv('DASHBOARD_HOST', '0.0.0.0')
    DASHBOARD_PORT = int(os.getenv('DASHBOARD_PORT', 8080))
    # How the dashboard is reached from outside, for links in emails.
    DASHBOARD_URL = (os.getenv('DASHBOARD_URL') or f"http://localhost:{DASHBOARD_PORT}").rstrip('/')
    DASHBOARD_USER = os.getenv('DASHBOARD_USER')
    DASHBOARD_PASS = os.getenv('DASHBOARD_PASS')
    DASHBOARD_ALLOW_REVEAL = _as_bool(os.getenv('DASHBOARD_ALLOW_REVEAL'), True)
    DASHBOARD_PAGE_SIZE = int(os.getenv('DASHBOARD_PAGE_SIZE', 24))

    REVIEW_DIR = os.getenv('REVIEW_DIR', 'review_images')
    REVIEW_DB_PATH = os.getenv('REVIEW_DB_PATH', 'review_queue.db')
    # Resolved items older than this are purged on startup (0 disables).
    REVIEW_RETENTION_DAYS = int(os.getenv('REVIEW_RETENTION_DAYS', 30))

    @classmethod
    def immich_enabled(cls):
        """Immich integration is active when the database is configured."""
        return bool(cls.IMMICH_DB_URL or (cls.IMMICH_DB_HOST and cls.IMMICH_DB_PASSWORD))

    @classmethod
    def path_map(cls):
        """
        Parse IMMICH_PATH_MAP into a list of (local_prefix, immich_prefix) pairs.

        Returns:
            list[tuple[str, str]]: Longest local prefix first.
        """
        pairs = []
        for entry in cls.IMMICH_PATH_MAP.split(','):
            entry = entry.strip()
            if not entry or ':' not in entry:
                continue
            local, remote = entry.split(':', 1)
            local = local.strip().rstrip('/')
            remote = remote.strip().rstrip('/')
            if local and remote:
                pairs.append((local, remote))
        return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)

    @classmethod
    def validate(cls):
        required = ['EMAIL_ADDRESS', 'SMTP_SERVER', 'SMTP_USER', 'SMTP_PASS']
        missing = [field for field in required if not getattr(cls, field)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        if cls.REDACTION_MODE not in ('blur', 'pixelate', 'box'):
            raise ValueError(f"REDACTION_MODE must be blur, pixelate or box (got '{cls.REDACTION_MODE}')")

        if cls.IMMICH_DELETE_MODE not in ('trash', 'permanent'):
            raise ValueError(f"IMMICH_DELETE_MODE must be trash or permanent (got '{cls.IMMICH_DELETE_MODE}')")

        if cls.IMMICH_DB_HOST and not cls.IMMICH_DB_PASSWORD and not cls.IMMICH_DB_URL:
            raise ValueError("IMMICH_DB_HOST is set but IMMICH_DB_PASSWORD is missing")

        if cls.immich_enabled() and not cls.IMMICH_EXTERNAL_URL:
            print("Warning: IMMICH_EXTERNAL_URL is not set, so Immich links will be omitted")
