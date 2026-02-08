"""
Browser-based scraper using Playwright for JavaScript-heavy pages.
Handles "Load More" buttons, infinite scroll, and dynamic content.
"""
import re
import time
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from config import Config


def scrape_with_browser(url: str, max_load_more_clicks: int = 50):
    """
    Generator that scrapes a page using a real browser.
    Handles "Load More" buttons and infinite scroll.
    
    Yields events like scrape_contacts_with_progress.
    """
    max_load_more_clicks = min(max_load_more_clicks, 100)  # Cap at 100
    
    # Validate URL
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        yield {'type': 'error', 'message': 'Invalid URL format. Please include http:// or https://'}
        return
    
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    yield {'type': 'progress', 'current': 0, 'total': 1, 'message': '🚀 Launching browser...'}
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            yield {'type': 'progress', 'current': 0, 'total': 1, 'message': '🔗 Loading page...'}
            
            try:
                page.goto(url, wait_until='networkidle', timeout=30000)
            except PlaywrightTimeout:
                # Try with just domcontentloaded if networkidle times out
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            yield {'type': 'progress', 'current': 1, 'total': 1, 'message': '✅ Page loaded'}
            
            # Step 1: Look for and click "Load More" buttons
            load_more_clicked = 0
            
            # Common "Load More" button selectors
            load_more_selectors = [
                'button:has-text("Load More")',
                'button:has-text("Show More")',
                'a:has-text("Load More")',
                'a:has-text("Show More")',
                '[class*="load-more"]',
                '[class*="loadmore"]', 
                '[class*="show-more"]',
                '[data-action="load-more"]',
                'button:has-text("View More")',
                'a:has-text("View More")',
            ]
            
            yield {'type': 'progress', 'current': 0, 'total': 1, 'message': '🔍 Checking for "Load More" buttons...'}
            
            # Try to find and click load more buttons
            found_load_more = False
            for selector in load_more_selectors:
                try:
                    button = page.locator(selector).first
                    if button.is_visible(timeout=2000):
                        found_load_more = True
                        break
                except:
                    continue
            
            if found_load_more:
                yield {'type': 'progress', 'current': 0, 'total': max_load_more_clicks, 
                       'message': '📥 Found "Load More" button. Loading all content...'}
                
                while load_more_clicked < max_load_more_clicks:
                    clicked = False
                    
                    for selector in load_more_selectors:
                        try:
                            button = page.locator(selector).first
                            if button.is_visible(timeout=1000):
                                # Get current page height
                                old_height = page.evaluate('document.body.scrollHeight')
                                
                                # Click the button
                                button.click()
                                load_more_clicked += 1
                                
                                yield {'type': 'progress', 'current': load_more_clicked, 
                                       'total': max_load_more_clicks,
                                       'message': f'📥 Clicked "Load More" ({load_more_clicked} times)...'}
                                
                                # Wait for new content
                                time.sleep(1)
                                page.wait_for_load_state('networkidle', timeout=5000)
                                
                                # Check if more content loaded
                                new_height = page.evaluate('document.body.scrollHeight')
                                if new_height > old_height:
                                    clicked = True
                                    break
                        except:
                            continue
                    
                    if not clicked:
                        # No more load more buttons or nothing new loaded
                        break
                
                yield {'type': 'progress', 'current': load_more_clicked, 'total': load_more_clicked,
                       'message': f'✅ Loaded all content ({load_more_clicked} clicks)'}
            else:
                # Try infinite scroll
                yield {'type': 'progress', 'current': 0, 'total': 1, 
                       'message': '📜 No "Load More" button. Checking for infinite scroll...'}
                
                # Scroll to bottom a few times to trigger any lazy loading
                for i in range(3):
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    time.sleep(0.5)
            
            # Step 2: Now extract all profile links from the fully loaded page
            yield {'type': 'progress', 'current': 0, 'total': 1, 'message': '🔍 Extracting profile links...'}
            
            # Get all links
            all_links = page.evaluate('''() => {
                const links = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    links.push({
                        href: a.href,
                        text: a.innerText.trim()
                    });
                });
                return links;
            }''')
            
            # Filter to profile links
            profile_links = []
            seen_urls = set()
            
            for link in all_links:
                href = link['href']
                text = link['text']
                
                if not looks_like_profile_url(href, url):
                    continue
                
                if href in seen_urls:
                    continue
                
                # Try to get name from link text or URL
                name = None
                if text and looks_like_name(text):
                    name = clean_name(text)
                else:
                    name = extract_name_from_url(href)
                
                if name and name != "Unknown":
                    profile_links.append((name, href))
                    seen_urls.add(href)
            
            yield {'type': 'progress', 'current': 0, 'total': len(profile_links),
                   'message': f'👥 Found {len(profile_links)} profiles'}
            
            # Step 3: Visit each profile to get emails
            contacts = []
            seen_emails = set()
            
            for idx, (name, profile_url) in enumerate(profile_links):
                yield {'type': 'progress', 'current': idx + 1, 'total': len(profile_links),
                       'message': f'📄 [{idx + 1}/{len(profile_links)}] Fetching: {name}'}
                
                try:
                    page.goto(profile_url, wait_until='domcontentloaded', timeout=15000)
                    
                    # Look for emails in page content
                    page_text = page.inner_text('body')
                    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                    
                    for match in re.finditer(email_pattern, page_text):
                        email = match.group().lower()
                        if is_valid_academic_email(email) and email not in seen_emails:
                            contact = {'name': name, 'email': email, 'source': profile_url}
                            contacts.append(contact)
                            seen_emails.add(email)
                            
                            yield {'type': 'contact', 'contact': contact, 'index': len(contacts),
                                   'message': f'✅ [{idx + 1}/{len(profile_links)}] Found: {name} - {email}'}
                            break
                    
                    if email not in seen_emails:
                        yield {'type': 'progress', 'current': idx + 1, 'total': len(profile_links),
                               'message': f'⚠️ [{idx + 1}/{len(profile_links)}] No email for: {name}'}
                    
                    time.sleep(0.3)  # Be nice to servers
                    
                except Exception as e:
                    yield {'type': 'progress', 'current': idx + 1, 'total': len(profile_links),
                           'message': f'⚠️ [{idx + 1}/{len(profile_links)}] Error: {name}'}
                    continue
            
            browser.close()
            
            yield {'type': 'progress', 'current': 1, 'total': 1,
                   'message': f'🎉 Done! Found {len(contacts)} contacts'}
            yield {'type': 'done', 'total': len(contacts)}
            
        except Exception as e:
            yield {'type': 'error', 'message': f'Browser error: {str(e)}'}
            return


def looks_like_profile_url(href: str, page_url: str) -> bool:
    """Check if a URL looks like it leads to a profile page."""
    href_lower = href.lower()
    
    # Skip external links, PDFs, images, etc.
    if any(ext in href_lower for ext in ['.pdf', '.jpg', '.png', '.doc', 'mailto:', 'tel:', 'javascript:', '#']):
        return False
    
    # Skip if it's the same as the current page
    if href == page_url or href == '':
        return False
    
    # Common profile URL patterns
    profile_patterns = ['/people/', '/person/', '/faculty/', '/staff/', '/student/', '/profile/', '/~', '/user/']
    if any(pattern in href_lower for pattern in profile_patterns):
        return True
    
    return False


def looks_like_name(text: str) -> bool:
    """Check if text looks like a person's name."""
    if not text or len(text) < 3 or len(text) > 60:
        return False
    
    if not any(c.isalpha() for c in text):
        return False
    
    text_lower = text.lower().strip()
    
    # Comprehensive filter for navigation/section items (NOT names)
    navigation_patterns = [
        # Single words
        'students', 'faculty', 'staff', 'people', 'members', 'team',
        'directory', 'all', 'next', 'previous', 'back', 'home', 'about',
        'research', 'publications', 'news', 'events', 'alumni', 'overview',
        'administration', 'leadership', 'department', 'lecturers', 'adjunct',
        'professor', 'associate', 'assistant',
        # Multi-word patterns
        'load more', 'show more', 'view all', 'see more', 'read more',
        'phd students', 'masters students', 'graduate students', 
        'undergraduate students', 'postdoctoral fellows', 'postdocs',
        'courtesy faculty', 'adjunct faculty', 'visiting faculty',
        'adjunct professor', 'associate professor', 'assistant professor',
        'research staff', 'administrative staff', 'in memoriam',
        'affiliated faculty', 'emeritus faculty', 'primary faculty',
        'core faculty', 'joint faculty', 'associated faculty',
        'clinical faculty', 'teaching faculty', 'senior lecturer'
    ]
    
    # Check exact match first
    if text_lower in navigation_patterns:
        return False
    
    # Check if any navigation phrase is contained in the text
    for pattern in navigation_patterns:
        if pattern in text_lower:
            return False
    
    if text[0].islower():
        return False
    
    words = text.split()
    if len(words) >= 2:
        return all(word[0].isupper() or word.lower() in ['de', 'van', 'von', 'la', 'le', 'del'] 
                   for word in words if word)
    
    return len(words) == 1 and len(text) >= 4


def clean_name(name: str) -> str:
    """Clean up a name string."""
    import re
    name = re.sub(r'\b(Dr\.?|Prof\.?|Professor|PhD|Ph\.D\.?|Mr\.?|Ms\.?|Mrs\.?)\b', '', name, flags=re.IGNORECASE)
    name = ' '.join(name.split())
    return name.strip() or "Unknown"


def extract_name_from_url(url: str) -> str:
    """Try to extract a person's name from a profile URL."""
    match = re.search(r'/(?:people|person|faculty|staff|profile|user|~)/([\w-]+)/?$', url.lower())
    if match:
        slug = match.group(1)
        parts = slug.replace('_', '-').split('-')
        if len(parts) >= 2 and all(len(p) >= 2 for p in parts):
            name = ' '.join(part.capitalize() for part in parts)
            return name
    return "Unknown"


def is_valid_academic_email(email: str) -> bool:
    """Check if email looks like a valid academic email."""
    email = email.lower()
    
    invalid_patterns = [
        'noreply', 'no-reply', 'admin@', 'info@', 'contact@',
        'support@', 'help@', 'webmaster', 'newsletter', 'example.com'
    ]
    
    if any(pattern in email for pattern in invalid_patterns):
        return False
    
    local_part = email.split('@')[0]
    if len(local_part) < 3:
        return False
    
    return True
