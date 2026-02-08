
import sys
import smtplib
from config import Config

print(f"Testing authentication for: {Config.GMAIL_ADDRESS}")
print(f"Server: {Config.SMTP_SERVER}:{Config.SMTP_PORT}")

try:
    with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
        server.starttls()
        server.login(Config.GMAIL_ADDRESS, Config.GMAIL_APP_PASSWORD)
        print("Authentication SUCCESS ✅")
except smtplib.SMTPAuthenticationError:
    print("Authentication FAILED ❌: Invalid credentials")
    sys.exit(1)
except Exception as e:
    print(f"Authentication FAILED ❌: {e}")
    sys.exit(1)
