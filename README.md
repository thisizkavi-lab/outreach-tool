# Outreach Automation Tool

A human-in-the-loop web application for contacting academic researchers. Built for prospective MS/PhD applicants who want to reach out for advice about funding, preparation, and research paths.

## Features

- 🔍 **URL Scraper** - Extract public academic emails and names from webpages
- 👥 **Contact Preview** - Review, edit, and select contacts before proceeding
- ✍️ **Template Editor** - Write email templates with `{name}` placeholder
- 👁️ **Email Preview** - See personalized emails for each contact
- 📅 **Scheduler** - Send immediately or schedule for later
- 📊 **Status Tracking** - View logs of all sent emails

## Design Principles

- **Human control over automation** - Every step requires explicit confirmation
- **Preview before action** - No blind sending or scraping
- **Quality over volume** - Rate-limited, respectful outreach

## Setup

### 1. Install Dependencies

```bash
cd primal-curiosity
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Gmail

1. Copy the template:
   ```bash
   cp .env.template .env
   ```

2. Enable 2-Factor Authentication on your Gmail account

3. Generate an App Password:
   - Go to [Google App Passwords](https://myaccount.google.com/apppasswords)
   - Select "Mail" and your device
   - Copy the 16-character password

4. Edit `.env` with your credentials:
   ```
   GMAIL_ADDRESS=your-email@gmail.com
   GMAIL_APP_PASSWORD=your-16-char-password
   FLASK_SECRET_KEY=any-random-string
   ```

### 3. Run the Application

```bash
python app.py
```

Open http://localhost:5000 in your browser.

## Usage Flow

1. **Scrape** - Paste an academic webpage URL (faculty page, lab members, etc.)
2. **Preview** - Review extracted contacts, edit names/emails, remove unwanted rows
3. **Template** - Write your email with `{name}` placeholder
4. **Preview Emails** - See each personalized email before sending
5. **Send/Schedule** - Send now (with delays) or schedule for later
6. **Status** - Track what was sent and view any errors

## Rate Limiting

- Default delay: 30-60 seconds between emails
- Daily limit: 50 emails (configurable in `.env`)
- Designed to avoid spam behavior

## Configuration Options

Edit `.env` to customize:

```
SEND_DELAY_MIN=30      # Minimum seconds between emails
SEND_DELAY_MAX=60      # Maximum seconds between emails
DAILY_SEND_LIMIT=50    # Maximum emails per day
FLASK_DEBUG=true       # Enable debug mode
```

## Security Notes

⚠️ **Important:**
- Never commit your `.env` file to git
- Use App Passwords, not your regular Gmail password
- Only scrape public academic pages
- Respect robots.txt and usage policies
- Use for legitimate academic outreach only

## Project Structure

```
primal-curiosity/
├── app.py              # Flask application
├── config.py           # Configuration from environment
├── database.py         # SQLite operations
├── scraper.py          # Web scraping logic
├── emailer.py          # Email sending engine
├── scheduler.py        # APScheduler integration
├── requirements.txt    # Python dependencies
├── .env.template       # Environment variable template
├── templates/          # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── preview.html
│   ├── template.html
│   ├── email_preview.html
│   ├── schedule.html
│   └── status.html
└── static/
    ├── style.css
    └── app.js
```

## Troubleshooting

**"Gmail not configured"**
- Make sure you copied `.env.template` to `.env`
- Verify your Gmail address and App Password are correct
- Ensure 2FA is enabled on your Google account

**"No contacts found"**
- The page might not have public emails
- Try a different faculty/lab page
- Check if the page requires login

**Emails failing to send**
- Check your daily limit hasn't been reached
- Verify your App Password is still valid
- Check the Status page for error messages

## License

For personal educational use only.
