"""
SQLite database operations for email logging.
"""
import sqlite3
from datetime import datetime
from typing import Optional
from config import Config


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT,
            status TEXT DEFAULT 'pending',
            scheduled_time DATETIME,
            sent_time DATETIME,
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()


def log_email(
    name: str,
    email: str,
    subject: str,
    body: str,
    status: str = 'pending',
    scheduled_time: Optional[datetime] = None
) -> int:
    """Log an email to the database. Returns the log ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO email_logs (name, email, subject, body, status, scheduled_time)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (name, email, subject, body, status, scheduled_time))
    
    log_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return log_id


def update_email_status(
    log_id: int,
    status: str,
    error_message: Optional[str] = None
):
    """Update the status of an email log."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if status == 'sent':
        cursor.execute('''
            UPDATE email_logs 
            SET status = ?, sent_time = ?, error_message = ?
            WHERE id = ?
        ''', (status, datetime.now(), error_message, log_id))
    else:
        cursor.execute('''
            UPDATE email_logs 
            SET status = ?, error_message = ?
            WHERE id = ?
        ''', (status, error_message, log_id))
    
    conn.commit()
    conn.close()


def get_all_logs(limit: int = 100) -> list:
    """Get all email logs, most recent first."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM email_logs 
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_pending_count() -> int:
    """Get count of pending emails."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM email_logs WHERE status = "pending"')
    count = cursor.fetchone()[0]
    conn.close()
    
    return count


def get_today_sent_count() -> int:
    """Get count of emails sent today."""
    conn = get_connection()
    cursor = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT COUNT(*) FROM email_logs 
        WHERE status = "sent" AND DATE(sent_time) = ?
    ''', (today,))
    
    count = cursor.fetchone()[0]
    conn.close()
    
    return count
