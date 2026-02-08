"""
Academic Outreach Automation Tool - Flask Application
Human-in-the-loop workflow: Scrape → Preview → Edit → Template → Preview → Schedule → Send
"""
import atexit
import csv
import io
import json
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, make_response

from config import Config
from database import init_db, log_email, get_all_logs, get_today_sent_count
from scraper import scrape_contacts, ScraperError
from emailer import render_template as render_email_template, validate_template, EmailError, send_batch, send_email
from scheduler import schedule_batch, get_scheduled_jobs, shutdown_scheduler, get_scheduler, cancel_job
from werkzeug.utils import secure_filename

# Initialize Flask app
app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

# Initialize database on startup
init_db()

# Initialize scheduler
get_scheduler()

# Cleanup on shutdown
atexit.register(shutdown_scheduler)


# ============================================================
# Request Middleware
# ============================================================

@app.before_request
def check_setup():
    """Ensure email is configured before allowing access to most routes."""
    # Allow access to settings, static files, and verification
    allowed_routes = ['settings', 'save_settings', 'verify_email', 'static']
    
    if request.endpoint and request.endpoint not in allowed_routes:
        if not Config.is_email_configured():
            flash('🚀 Welcome! Let\'s setup your email first so you can start outreach.', 'info')
            return redirect(url_for('settings'))


# ============================================================
# Routes
# ============================================================

@app.route('/')
def index():
    """Landing page with URL input."""
    return render_template('index.html')


@app.route('/scrape', methods=['GET'])
def scrape_page():
    """Show the scraping page with terminal."""
    return render_template('scrape.html')


@app.route('/scrape_stream')
def scrape_stream():
    """SSE endpoint for real-time scraping progress."""
    url = request.args.get('url', '').strip()
    max_profiles = request.args.get('max_profiles', '100')
    
    # Parse max_profiles
    try:
        max_profiles = int(max_profiles)
        max_profiles = max(10, min(max_profiles, 1000))
    except (ValueError, TypeError):
        max_profiles = 100
    
    def generate():
        """Generator that yields SSE events."""
        if not url:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Please enter a URL'})}\n\n"
            return
        
        try:
            # Use the scraper with progress callback
            all_contacts = []
            
            def progress_callback(current, total, message):
                event_data = {
                    'type': 'progress',
                    'current': current,
                    'total': total,
                    'message': message
                }
                return f"data: {json.dumps(event_data)}\n\n"
            
            # Start scraping with progress updates
            from scraper import scrape_contacts_with_progress
            
            for event in scrape_contacts_with_progress(url, max_profiles):
                if event['type'] == 'progress':
                    yield f"data: {json.dumps(event)}\n\n"
                elif event['type'] == 'contact':
                    all_contacts.append(event['contact'])
                    yield f"data: {json.dumps(event)}\n\n"
                elif event['type'] == 'done':
                    # Store contacts in a temporary location (can't use session in generator)
                    app.config['TEMP_CONTACTS'] = all_contacts
                    app.config['TEMP_SOURCE_URL'] = url
                    yield f"data: {json.dumps({'type': 'done', 'total': len(all_contacts)})}\n\n"
                elif event['type'] == 'error':
                    yield f"data: {json.dumps(event)}\n\n"
                    
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/scrape_browser_stream')
def scrape_browser_stream():
    """SSE endpoint for browser-based scraping (handles Load More buttons)."""
    url = request.args.get('url', '').strip()
    
    def generate():
        if not url:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Please enter a URL'})}\n\n"
            return
        
        try:
            from browser_scraper import scrape_with_browser
            all_contacts = []
            
            for event in scrape_with_browser(url, max_load_more_clicks=50):
                if event['type'] == 'progress':
                    yield f"data: {json.dumps(event)}\n\n"
                elif event['type'] == 'contact':
                    all_contacts.append(event['contact'])
                    yield f"data: {json.dumps(event)}\n\n"
                elif event['type'] == 'done':
                    app.config['TEMP_CONTACTS'] = all_contacts
                    app.config['TEMP_SOURCE_URL'] = url
                    yield f"data: {json.dumps({'type': 'done', 'total': len(all_contacts)})}\n\n"
                elif event['type'] == 'error':
                    yield f"data: {json.dumps(event)}\n\n"
                    
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/scrape_complete', methods=['POST'])
def scrape_complete():
    """Called after SSE scraping completes to store contacts in session."""
    contacts = app.config.get('TEMP_CONTACTS', [])
    source_url = app.config.get('TEMP_SOURCE_URL', '')
    
    if contacts:
        session['contacts'] = contacts
        session['source_url'] = source_url
        # Clear temp storage
        app.config['TEMP_CONTACTS'] = []
        app.config['TEMP_SOURCE_URL'] = ''
        return jsonify({'success': True, 'count': len(contacts)})
    else:
        return jsonify({'success': False, 'error': 'No contacts found'})


# ============================================================
# EXPORT ROUTES
# ============================================================

@app.route('/export/csv')
def export_csv():
    """Export contacts as CSV file."""
    contacts = session.get('contacts', [])
    
    if not contacts:
        flash('No contacts to export. Please scrape a URL first.', 'warning')
        return redirect(url_for('index'))
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['name', 'email', 'source'])
    writer.writeheader()
    writer.writerows(contacts)
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=contacts.csv'
    
    return response


@app.route('/export/json')
def export_json():
    """Export contacts as JSON file."""
    contacts = session.get('contacts', [])
    
    if not contacts:
        flash('No contacts to export. Please scrape a URL first.', 'warning')
        return redirect(url_for('index'))
    
    # Create JSON response
    response = make_response(json.dumps(contacts, indent=2))
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = 'attachment; filename=contacts.json'
    
    return response


# ============================================================
# EMAIL SETTINGS ROUTES
# ============================================================

@app.route('/settings')
def settings():
    """Email settings page."""
    # Check if email is configured
    email_configured = bool(Config.GMAIL_ADDRESS and Config.GMAIL_APP_PASSWORD)
    current_email = Config.GMAIL_ADDRESS if email_configured else None
    
    return render_template('settings.html', 
                         email_configured=email_configured,
                         current_email=current_email,
                         cv_filename=Config.CV_FILENAME,
                         cv_enabled=Config.CV_ENABLED)


@app.route('/settings/save', methods=['POST'])
def save_settings():
    """Save email settings."""
    email = request.form.get('email', '').strip()
    # Remove spaces from password as Google often shows them with spaces
    app_password = request.form.get('app_password', '').strip().replace(' ', '')
    
    if not email or not app_password:
        flash('Both email and app password are required.', 'error')
        return redirect(url_for('settings'))
    
    # Validate email format
    import re
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        flash('Invalid email format.', 'error')
        return redirect(url_for('settings'))
    
    # Update .env file
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    
    # Read existing content
    env_content = {}
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    env_content[key] = value
    
    # Update email settings
    env_content['GMAIL_ADDRESS'] = email
    env_content['GMAIL_APP_PASSWORD'] = app_password
    
    # Write back
    with open(env_path, 'w') as f:
        for key, value in env_content.items():
            f.write(f'{key}={value}\n')
    
    # Update Config
    Config.GMAIL_ADDRESS = email
    Config.GMAIL_APP_PASSWORD = app_password
    
    flash('Email settings saved! Testing connection...', 'success')
    return redirect(url_for('verify_email'))


@app.route('/settings/upload_cv', methods=['POST'])
def upload_cv():
    """Handle CV upload."""
    if 'cv_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('settings'))
    
    file = request.files['cv_file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('settings'))
        
    if file and file.filename.lower().endswith('.pdf'):
        filename = secure_filename(file.filename)
        file.save(os.path.join(Config.UPLOAD_FOLDER, filename))
        
        # Update .env
        update_env_key('CV_FILENAME', filename)
        Config.CV_FILENAME = filename
        
        # Auto-enable CV if not enabled
        if not Config.CV_ENABLED:
            update_env_key('CV_ENABLED', 'true')
            Config.CV_ENABLED = True
        
        flash('CV uploaded successfully', 'success')
    else:
        flash('Invalid file type. Only PDF allowed.', 'error')
        
    return redirect(url_for('settings'))


@app.route('/settings/toggle_cv', methods=['POST'])
def toggle_cv():
    """Toggle CV attachment on/off."""
    enabled = request.form.get('cv_enabled') == 'on'
    update_env_key('CV_ENABLED', str(enabled).lower())
    Config.CV_ENABLED = enabled
    flash(f'CV Attachment {"Enabled" if enabled else "Disabled"}', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/remove_cv', methods=['POST'])
def remove_cv():
    """Remove current CV."""
    if Config.CV_FILENAME:
        # We don't delete the file, just unset it in config/env
        update_env_key('CV_FILENAME', '')
        update_env_key('CV_ENABLED', 'false') # Disable toggle
        Config.CV_FILENAME = None
        Config.CV_ENABLED = False
        flash('CV removed and attachment disabled.', 'success')
    return redirect(url_for('settings'))


def update_env_key(key, value):
    """Update a specific key in .env file."""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    
    # Read existing
    env_content = {}
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env_content[k] = v
    
    # Update key
    env_content[key] = value
    
    # Write back
    with open(env_path, 'w') as f:
        for k, v in env_content.items():
            f.write(f'{k}={v}\n')


@app.route('/settings/verify')
def verify_email():
    """Verify email configuration by sending a test email."""
    if not Config.GMAIL_ADDRESS or not Config.GMAIL_APP_PASSWORD:
        flash('Email not configured. Please enter your credentials first.', 'error')
        return redirect(url_for('settings'))
    
    try:
        # Try to send a test email to yourself
        from emailer import send_email
        
        send_email(
            to_email=Config.GMAIL_ADDRESS,
            to_name="User",
            subject='Academic Outreach - Email Setup Verified ✅',
            body=f'''Hello!

Your email is now configured correctly for the Academic Outreach Tool.

Setup Details:
- Email: {Config.GMAIL_ADDRESS}
- Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

You can now use this tool to send personalized outreach emails to academic contacts.

Best regards,
Academic Outreach Tool'''
        )
        
        flash(f'✅ Email verified! A test email was sent to {Config.GMAIL_ADDRESS}', 'success')
        
    except Exception as e:
        flash(f'❌ Email verification failed: {str(e)}. Please check your credentials.', 'error')
    
    return redirect(url_for('settings'))


@app.route('/preview')
def preview():
    """Preview and edit scraped contacts."""
    contacts = session.get('contacts', [])
    source_url = session.get('source_url', '')
    
    if not contacts:
        flash('No contacts to preview. Please scrape a URL first.', 'warning')
        return redirect(url_for('index'))
    
    return render_template('preview.html', contacts=contacts, source_url=source_url)


@app.route('/update_contacts', methods=['POST'])
def update_contacts():
    """Update contacts from preview page edits."""
    data = request.get_json()
    
    if not data or 'contacts' not in data:
        return jsonify({'error': 'Invalid data'}), 400
    
    session['contacts'] = data['contacts']
    return jsonify({'success': True})


@app.route('/template')
def template():
    """Email template editor."""
    contacts = session.get('contacts', [])
    
    if not contacts:
        flash('No contacts selected. Please scrape and select contacts first.', 'warning')
        return redirect(url_for('index'))
    
    # Load existing template from session or use default
    subject = session.get('email_subject', '')
    body = session.get('email_body', '''Dear {name},

I hope this email finds you well. My name is [Your Name], and I am a prospective [MS/PhD] applicant interested in [field/topic].

I came across your work on [specific topic/paper] and was impressed by [specific aspect]. I would be grateful for any advice you might have about [specific question].

Thank you for your time, and I apologize for any inconvenience.

Best regards,
[Your Name]''')
    
    return render_template('template.html', 
                         subject=subject, 
                         body=body, 
                         contact_count=len(contacts))


@app.route('/save_template', methods=['POST'])
def save_template():
    """Save email template to session."""
    subject = request.form.get('subject', '').strip()
    body = request.form.get('body', '').strip()
    
    if not subject or not body:
        flash('Subject and body are required', 'error')
        return redirect(url_for('template'))
    
    # Validate template
    validation = validate_template(body)
    if not validation['valid']:
        for error in validation['errors']:
            flash(error, 'error')
        return redirect(url_for('template'))
    
    session['email_subject'] = subject
    session['email_body'] = body
    
    return redirect(url_for('email_preview'))


@app.route('/email_preview')
def email_preview():
    """Preview personalized emails for each contact."""
    contacts = session.get('contacts', [])
    subject = session.get('email_subject', '')
    body = session.get('email_body', '')
    
    if not contacts:
        flash('No contacts available', 'warning')
        return redirect(url_for('index'))
    
    if not subject or not body:
        flash('Please create an email template first', 'warning')
        return redirect(url_for('template'))
    
    # Render personalized previews
    previews = []
    for contact in contacts:
        variables = {'name': contact['name']}
        rendered_subject = render_email_template(subject, variables)
        rendered_body = render_email_template(body, variables)
        
        previews.append({
            'name': contact['name'],
            'email': contact['email'],
            'subject': rendered_subject,
            'body': rendered_body
        })
    
    return render_template('email_preview.html', previews=previews)


@app.route('/schedule')
def schedule():
    """Scheduling page with datetime picker."""
    contacts = session.get('contacts', [])
    subject = session.get('email_subject', '')
    
    if not contacts or not subject:
        flash('Please complete previous steps first', 'warning')
        return redirect(url_for('index'))
    
    email_configured = Config.is_email_configured()
    today_sent = get_today_sent_count()
    daily_limit = Config.DAILY_SEND_LIMIT
    
    return render_template('schedule.html',
                         contact_count=len(contacts),
                         email_configured=email_configured,
                         today_sent=today_sent,
                         daily_limit=daily_limit)


@app.route('/send_now', methods=['POST'])
def send_now():
    """Send emails immediately with rate limiting."""
    contacts = session.get('contacts', [])
    subject = session.get('email_subject', '')
    body = session.get('email_body', '')
    
    if not contacts or not subject or not body:
        flash('Missing email data', 'error')
        return redirect(url_for('schedule'))
    
    if not Config.is_email_configured():
        flash('Gmail not configured. Check your .env file.', 'error')
        return redirect(url_for('schedule'))
    
    # Prepare emails
    emails = []
    for contact in contacts:
        variables = {'name': contact['name']}
        rendered_subject = render_email_template(subject, variables)
        rendered_body = render_email_template(body, variables)
        
        # Log to database
        log_id = log_email(
            name=contact['name'],
            email=contact['email'],
            subject=rendered_subject,
            body=rendered_body,
            status='pending'
        )
        
        emails.append({
            'to_email': contact['email'],
            'to_name': contact['name'],
            'subject': rendered_subject,
            'body': rendered_body,
            'log_id': log_id
        })
    
    # Send with delays
    results = send_batch(emails, delay_between=True)
    
    # Clear session data
    session.pop('contacts', None)
    session.pop('email_subject', None)
    session.pop('email_body', None)
    
    flash(f"Sent {results['sent']} email(s), {results['failed']} failed", 
          'success' if results['failed'] == 0 else 'warning')
    
    return redirect(url_for('status'))


@app.route('/schedule_send', methods=['POST'])
def schedule_send():
    """Schedule emails for later sending."""
    contacts = session.get('contacts', [])
    subject = session.get('email_subject', '')
    body = session.get('email_body', '')
    
    send_datetime = request.form.get('send_datetime', '')
    
    if not contacts or not subject or not body:
        flash('Missing email data', 'error')
        return redirect(url_for('schedule'))
    
    if not send_datetime:
        flash('Please select a date and time', 'error')
        return redirect(url_for('schedule'))
    
    if not Config.is_email_configured():
        flash('Gmail not configured. Check your .env file.', 'error')
        return redirect(url_for('schedule'))
    
    try:
        # Parse datetime
        send_time = datetime.fromisoformat(send_datetime)
        
        if send_time <= datetime.now():
            flash('Scheduled time must be in the future', 'error')
            return redirect(url_for('schedule'))
        
        # Prepare emails
        emails = []
        for contact in contacts:
            variables = {'name': contact['name']}
            rendered_subject = render_email_template(subject, variables)
            rendered_body = render_email_template(body, variables)
            
            emails.append({
                'to_email': contact['email'],
                'to_name': contact['name'],
                'subject': rendered_subject,
                'body': rendered_body
            })
        
        # Schedule batch
        job_ids = schedule_batch(emails, send_time)
        
        # Clear session data
        session.pop('contacts', None)
        session.pop('email_subject', None)
        session.pop('email_body', None)
        
        flash(f"Scheduled {len(job_ids)} email(s) for {send_time.strftime('%Y-%m-%d %H:%M')}", 'success')
        
    except ValueError as e:
        flash(f'Invalid date/time format: {e}', 'error')
        return redirect(url_for('schedule'))
    
    return redirect(url_for('status'))


@app.route('/status')
def status():
    """View email logs and status."""
    logs = get_all_logs()
    scheduled_jobs = get_scheduled_jobs()
    today_sent = get_today_sent_count()
    
    return render_template('status.html',
                         logs=logs,
                         scheduled_jobs=scheduled_jobs,
                         today_sent=today_sent,
                         daily_limit=Config.DAILY_SEND_LIMIT)


@app.route('/api/logs')
def api_logs():
    """API endpoint for logs (for potential AJAX refresh)."""
    logs = get_all_logs()
    return jsonify(logs)


@app.route('/test_page')
def test_page():
    """Serve test faculty page for local testing."""
    return '''<!DOCTYPE html>
<html>
<head><title>Test Faculty Page</title></head>
<body>
    <h1>Computer Science Faculty</h1>
    
    <div class="faculty-member">
        <h2>Dr. Jane Smith</h2>
        <p>Professor of Machine Learning</p>
        <p>Email: <a href="mailto:jsmith@stanford.edu">jsmith@stanford.edu</a></p>
    </div>
    
    <div class="faculty-member">
        <h2>Dr. John Doe</h2>
        <p>Associate Professor of Systems</p>
        <p>Contact: <a href="mailto:johndoe@mit.edu">johndoe@mit.edu</a></p>
    </div>
    
    <div class="faculty-member">
        <h2>Prof. Alice Johnson</h2>
        <p>Assistant Professor of AI</p>
        <p>Email: <a href="mailto:alice.johnson@berkeley.edu">alice.johnson@berkeley.edu</a></p>
    </div>
    
    <div class="faculty-member">
        <h2>Dr. Bob Williams</h2>
        <p>Professor of Robotics</p>
        <p><a href="mailto:bwilliams@cmu.edu?subject=Inquiry">Contact Me</a></p>
    </div>
    
    <div class="faculty-member">
        <h2>Dr. Maria Garcia</h2>
        <p>Associate Professor of NLP</p>
        <p>Email: mgarcia@princeton.edu</p>
    </div>
</body>
</html>'''


# ============================================================
# Error Handlers
# ============================================================

@app.errorhandler(404)
def not_found(e):
    flash('Page not found', 'error')
    return redirect(url_for('index'))


@app.errorhandler(500)
def server_error(e):
    flash('An error occurred. Please try again.', 'error')
    return redirect(url_for('index'))


# ============================================================
# Run
# ============================================================

if __name__ == '__main__':
    app.run(debug=Config.DEBUG, port=5000)
