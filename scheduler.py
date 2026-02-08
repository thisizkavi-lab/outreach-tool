"""
APScheduler integration for scheduling email jobs.
"""
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from emailer import send_email, EmailError
from database import log_email, update_email_status

# Global scheduler instance
scheduler = None


def get_scheduler() -> BackgroundScheduler:
    """Get or create the background scheduler."""
    global scheduler
    if scheduler is None:
        scheduler = BackgroundScheduler(
            jobstores={'default': MemoryJobStore()},
            job_defaults={'coalesce': True, 'max_instances': 1}
        )
        scheduler.start()
    return scheduler


def schedule_email(
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    send_time: datetime
) -> str:
    """
    Schedule an email to be sent at a specific time.
    
    Args:
        to_email: Recipient email
        to_name: Recipient name
        subject: Email subject
        body: Email body
        send_time: When to send the email
        
    Returns:
        Job ID for tracking
    """
    # Log the email as pending
    log_id = log_email(
        name=to_name,
        email=to_email,
        subject=subject,
        body=body,
        status='scheduled',
        scheduled_time=send_time
    )
    
    # Schedule the job
    sched = get_scheduler()
    job = sched.add_job(
        func=_send_scheduled_email,
        trigger='date',
        run_date=send_time,
        args=[to_email, to_name, subject, body, log_id],
        id=f'email_{log_id}'
    )
    
    return job.id


def _send_scheduled_email(
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    log_id: int
):
    """Internal function to send a scheduled email."""
    try:
        send_email(to_email, to_name, subject, body, log_id)
    except EmailError as e:
        # Error is already logged by send_email
        pass


def schedule_batch(
    emails: list[dict],
    start_time: datetime,
    delay_seconds: int = 45
) -> list[str]:
    """
    Schedule a batch of emails with staggered send times.
    
    Args:
        emails: List of email dicts with to_email, to_name, subject, body
        start_time: When to start sending
        delay_seconds: Seconds between each email
        
    Returns:
        List of job IDs
    """
    from datetime import timedelta
    
    job_ids = []
    current_time = start_time
    
    for email_data in emails:
        job_id = schedule_email(
            to_email=email_data['to_email'],
            to_name=email_data['to_name'],
            subject=email_data['subject'],
            body=email_data['body'],
            send_time=current_time
        )
        job_ids.append(job_id)
        current_time += timedelta(seconds=delay_seconds)
    
    return job_ids


def get_scheduled_jobs() -> list:
    """Get list of all scheduled jobs."""
    sched = get_scheduler()
    jobs = sched.get_jobs()
    
    return [{
        'id': job.id,
        'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
        'name': job.name
    } for job in jobs]


def cancel_job(job_id: str) -> bool:
    """Cancel a scheduled job."""
    sched = get_scheduler()
    try:
        sched.remove_job(job_id)
        return True
    except:
        return False


def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=True)
        scheduler = None
