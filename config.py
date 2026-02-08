"""
Configuration settings loaded from environment variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration from environment variables."""
    
    # Flask
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    # Gmail SMTP
    GMAIL_ADDRESS = os.getenv('GMAIL_ADDRESS', '')
    GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', '')
    SMTP_SERVER = 'smtp.gmail.com'
    SMTP_PORT = 587
    
    # Email Settings
    SEND_DELAY_MIN = int(os.getenv('SEND_DELAY_MIN', 30))
    SEND_DELAY_MAX = int(os.getenv('SEND_DELAY_MAX', 60))
    DAILY_SEND_LIMIT = int(os.getenv('DAILY_SEND_LIMIT', 50))
    
    # Database
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'outreach.db')
    
    # Scraper
    SCRAPE_TIMEOUT = 10  # seconds
    
    @classmethod
    def is_email_configured(cls) -> bool:
        """Check if Gmail credentials are configured."""
        return bool(cls.GMAIL_ADDRESS and cls.GMAIL_APP_PASSWORD)
    
    # Uploads
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    ALLOWED_EXTENSIONS = {'pdf'}
    CV_FILENAME = os.getenv('CV_FILENAME', None)
    CV_ENABLED = os.getenv('CV_ENABLED', 'false').lower() == 'true'
