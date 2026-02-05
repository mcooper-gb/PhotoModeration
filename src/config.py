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


    @classmethod
    def validate(cls):
        required = ['EMAIL_ADDRESS', 'SMTP_SERVER', 'SMTP_USER', 'SMTP_PASS']
        missing = [field for field in required if not getattr(cls, field)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
