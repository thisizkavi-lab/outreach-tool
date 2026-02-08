"""
Email sending engine with Gmail SMTP and rate limiting.
"""
import smtplib
import time
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from config import Config
from database import update_email_status, get_today_sent_count


class EmailError(Exception):
    """Custom exception for email errors."""
    pass


def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    log_id: Optional[int] = None
) -> bool:
    """
    Send a single email via Gmail SMTP.
    
    Args:
        to_email: Recipient email address
        to_name: Recipient name
        subject: Email subject
        body: Email body (already personalized)
        log_id: Optional database log ID to update
        
    Returns:
        True if sent successfully
        
    Raises:
        EmailError: If sending fails
    """
    if not Config.is_email_configured():
        raise EmailError("Gmail credentials not configured. Check your .env file.")
    
    # Check daily limit
    if get_today_sent_count() >= Config.DAILY_SEND_LIMIT:
        error_msg = f"Daily send limit ({Config.DAILY_SEND_LIMIT}) reached"
        if log_id:
            update_email_status(log_id, 'failed', error_msg)
        raise EmailError(error_msg)
    
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = Config.GMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach CV if enabled
        if Config.CV_ENABLED and Config.CV_FILENAME:
            import os
            from email.mime.base import MIMEBase
            from email import encoders
            
            cv_path = os.path.join(Config.UPLOAD_FOLDER, Config.CV_FILENAME)
            if os.path.exists(cv_path):
                try:
                    with open(cv_path, 'rb') as f:
                        part = MIMEBase('application', 'pdf')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header('Content-Disposition', f'attachment; filename="{Config.CV_FILENAME}"')
                        msg.attach(part)
                except Exception as e:
                    # Log error but send email anyway? Or fail?
                    # Let's log it or append to error_msg, but failing might be safer if user expects it.
                    # Since send_email returns bool/raises, let's raise for now if critical attachment fails.
                    raise EmailError(f"Failed to attach CV: {str(e)}")
            else:
                 # File missing but enabled? Warn or skip?
                 # Let's skip and log a warning if possible, but we don't have a logger here really.
                 # Actually, raising error is better so user knows something is wrong.
                 raise EmailError(f"CV attachment enabled but file not found: {Config.CV_FILENAME}")

        # Send via SMTP
        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.GMAIL_ADDRESS, Config.GMAIL_APP_PASSWORD)
            server.send_message(msg)
        
        # Update log on success
        if log_id:
            update_email_status(log_id, 'sent')
        
        return True
        
    except smtplib.SMTPAuthenticationError:
        error_msg = "Gmail authentication failed. Check your App Password."
        if log_id:
            update_email_status(log_id, 'failed', error_msg)
        raise EmailError(error_msg)
    except smtplib.SMTPException as e:
        error_msg = f"SMTP error: {str(e)}"
        if log_id:
            update_email_status(log_id, 'failed', error_msg)
        raise EmailError(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        if log_id:
            update_email_status(log_id, 'failed', error_msg)
        raise EmailError(error_msg)


def send_batch(emails: list[dict], delay_between: bool = True) -> dict:
    """
    Send a batch of emails with rate limiting.
    
    Args:
        emails: List of dicts with 'to_email', 'to_name', 'subject', 'body', 'log_id'
        delay_between: Whether to add delays between sends
        
    Returns:
        Dict with 'sent', 'failed', 'errors' counts
    """
    results = {'sent': 0, 'failed': 0, 'errors': []}
    
    for i, email_data in enumerate(emails):
        try:
            send_email(
                to_email=email_data['to_email'],
                to_name=email_data['to_name'],
                subject=email_data['subject'],
                body=email_data['body'],
                log_id=email_data.get('log_id')
            )
            results['sent'] += 1
            
        except EmailError as e:
            results['failed'] += 1
            results['errors'].append({
                'email': email_data['to_email'],
                'error': str(e)
            })
        
        # Add delay between sends (except for last email)
        if delay_between and i < len(emails) - 1:
            delay = random.randint(Config.SEND_DELAY_MIN, Config.SEND_DELAY_MAX)
            time.sleep(delay)
    
    return results


def render_template(template: str, variables: dict) -> str:
    """
    Render an email template with variable substitution.
    
    Args:
        template: Template string with {variable} placeholders
        variables: Dict of variable name -> value
        
    Returns:
        Rendered string
    """
    result = template
    for key, value in variables.items():
        result = result.replace('{' + key + '}', str(value))
    return result


def validate_template(template: str, required_vars: list[str] = None) -> dict:
    """
    Validate a template string.
    
    Args:
        template: Template string to validate
        required_vars: List of required variable names
        
    Returns:
        Dict with 'valid', 'placeholders', 'errors'
    """
    import re
    
    # Find all placeholders
    placeholders = re.findall(r'\{(\w+)\}', template)
    
    errors = []
    
    # Check for required variables
    if required_vars:
        for var in required_vars:
            if var not in placeholders:
                errors.append(f"Missing required placeholder: {{{var}}}")
    
    # Check for unclosed braces
    if template.count('{') != template.count('}'):
        errors.append("Mismatched braces in template")
    
    return {
        'valid': len(errors) == 0,
        'placeholders': list(set(placeholders)),
        'errors': errors
    }
