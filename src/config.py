import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SCAN_DIR = os.getenv('SCAN_DIR', '.')
    EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
    SMTP_SERVER = os.getenv('SMTP_SERVER')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER')
    SMTP_PASS = os.getenv('SMTP_PASS')
    DB_PATH = os.getenv('DB_PATH', 'scanned_images.db')
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', 10))
    CENSORED_DIR = os.getenv('CENSORED_DIR', 'censored_images')

    @classmethod
    def validate(cls):
        required = ['EMAIL_ADDRESS', 'SMTP_SERVER', 'SMTP_USER', 'SMTP_PASS']
        missing = [field for field in required if not getattr(cls, field)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
