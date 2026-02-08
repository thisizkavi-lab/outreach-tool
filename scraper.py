"""
Web scraper for extracting academic contacts (names and emails) from public pages.
Supports deep scraping - following profile links to find emails.
"""
import re
import ssl
import time
import urllib3
from urllib.parse import urlparse, urljoin
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
from config import Config

# Suppress SSL warnings when verification is disabled
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ScraperError(Exception):
    """Custom exception for scraping errors."""
    pass


# Common headers for all requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}


def fetch_page(url: str, timeout: int = 10) -> requests.Response:
    """Fetch a page with SSL fallback."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout, verify=True)
    except requests.exceptions.SSLError:
        response = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
    response.raise_for_status()
    return response


def scrape_contacts_with_progress(url: str, max_profiles: int = 100):
    """
    Generator that yields progress events during scraping.
    
    Yields dicts with:
    - {'type': 'progress', 'current': N, 'total': M, 'message': '...'}
    - {'type': 'contact', 'contact': {...}, 'index': N}
    - {'type': 'done', 'total': N}
    - {'type': 'error', 'message': '...'}
    """
    max_profiles = min(max_profiles, 1000)
    
    # Validate URL
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        yield {'type': 'error', 'message': 'Invalid URL format. Please include http:// or https://'}
        return
    
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    # Step 1: Fetch main page
    yield {'type': 'progress', 'current': 0, 'total': 1, 'message': '🔗 Connecting to webpage...'}
    
    try:
        response = fetch_page(url, timeout=Config.SCRAPE_TIMEOUT)
    except requests.Timeout:
        yield {'type': 'error', 'message': f'Request timed out after {Config.SCRAPE_TIMEOUT} seconds.'}
        return
    except requests.exceptions.ConnectionError:
        yield {'type': 'error', 'message': 'Could not connect to the website. Please check the URL.'}
        return
    except requests.HTTPError as e:
        yield {'type': 'error', 'message': f'HTTP error {e.response.status_code}'}
        return
    except requests.RequestException as e:
        yield {'type': 'error', 'message': f'Failed to fetch page: {str(e)}'}
        return
    
    yield {'type': 'progress', 'current': 1, 'total': 1, 'message': '✅ Webpage loaded successfully'}
    
    soup = BeautifulSoup(response.text, 'html.parser')
    contacts = []
    seen_emails = set()
    contact_index = 0
    
    # Step 2: Scan main page
    yield {'type': 'progress', 'current': 0, 'total': 1, 'message': '🔍 Scanning main page for emails...'}
    
    main_page_contacts = extract_contacts_from_soup(soup, url, seen_emails)
    
    if main_page_contacts:
        yield {'type': 'progress', 'current': 0, 'total': 1, 'message': f'📧 Found {len(main_page_contacts)} emails on main page'}
        for c in main_page_contacts:
            contact_index += 1
            contacts.append(c)
            yield {'type': 'contact', 'contact': c, 'index': contact_index}
    else:
        yield {'type': 'progress', 'current': 0, 'total': 1, 'message': '⚠️ No emails found on main page'}
    
    # Step 3: Deep scrape if no emails on main page
    if len(contacts) == 0:
        yield {'type': 'progress', 'current': 0, 'total': 1, 'message': '🔗 Finding profile links...'}
        
        # Check for pagination first
        all_page_urls = find_pagination_links(soup, base_url, url)
        all_profile_links = []
        
        if all_page_urls:
            yield {'type': 'progress', 'current': 0, 'total': len(all_page_urls), 
                   'message': f'📑 Found {len(all_page_urls)} pages. Scanning all pages...'}
            
            # Collect profiles from all pages
            for page_idx, page_url in enumerate(all_page_urls):
                yield {'type': 'progress', 'current': page_idx + 1, 'total': len(all_page_urls),
                       'message': f'📑 Scanning page {page_idx + 1}/{len(all_page_urls)}...'}
                
                try:
                    if page_url != url:  # Don't re-fetch the first page
                        page_response = fetch_page(page_url, timeout=Config.SCRAPE_TIMEOUT)
                        page_soup = BeautifulSoup(page_response.text, 'html.parser')
                    else:
                        page_soup = soup
                    
                    page_profiles = find_profile_links(page_soup, base_url, page_url)
                    all_profile_links.extend(page_profiles)
                    time.sleep(0.3)  # Be nice to the server
                except Exception:
                    continue
        else:
            all_profile_links = find_profile_links(soup, base_url, url)
        
        # Remove duplicates while preserving order
        seen_profile_urls = set()
        unique_profiles = []
        for name, profile_url in all_profile_links:
            if profile_url not in seen_profile_urls:
                unique_profiles.append((name, profile_url))
                seen_profile_urls.add(profile_url)
        
        if not unique_profiles:
            yield {'type': 'progress', 'current': 0, 'total': 1, 'message': '❌ No profile links found on this page'}
            yield {'type': 'done', 'total': 0}
            return
        
        total_profiles = min(len(unique_profiles), max_profiles)
        yield {'type': 'progress', 'current': 0, 'total': total_profiles, 
               'message': f'👥 Found {len(unique_profiles)} people. Scanning {total_profiles} profiles...'}
        
        # Visit each profile
        for idx, (name, profile_url) in enumerate(unique_profiles[:max_profiles]):
            yield {'type': 'progress', 'current': idx + 1, 'total': total_profiles,
                   'message': f'📄 [{idx + 1}/{total_profiles}] Fetching: {name}'}
            
            try:
                profile_contacts = scrape_profile_page(profile_url, name, seen_emails)
                
                for c in profile_contacts:
                    contact_index += 1
                    contacts.append(c)
                    yield {'type': 'contact', 'contact': c, 'index': contact_index,
                           'message': f'✅ [{idx + 1}/{total_profiles}] Found: {c["name"]} - {c["email"]}'}
                
                if not profile_contacts:
                    yield {'type': 'progress', 'current': idx + 1, 'total': total_profiles,
                           'message': f'⚠️ [{idx + 1}/{total_profiles}] No email for: {name}'}
                
                # Small delay
                if idx < total_profiles - 1:
                    time.sleep(0.3)
                    
            except Exception as e:
                yield {'type': 'progress', 'current': idx + 1, 'total': total_profiles,
                       'message': f'⚠️ [{idx + 1}/{total_profiles}] Error fetching: {name}'}
                continue
    
    yield {'type': 'progress', 'current': 1, 'total': 1, 
           'message': f'🎉 Done! Found {len(contacts)} contacts'}
    yield {'type': 'done', 'total': len(contacts)}


def find_pagination_links(soup: BeautifulSoup, base_url: str, current_url: str) -> list[str]:
    """
    Find pagination links (Page 1, 2, 3... or Next links).
    Returns list of page URLs including the current one.
    """
    page_urls = [current_url]  # Always include current page
    seen_urls = {current_url}
    
    # Common pagination patterns to look for
    pagination_containers = soup.find_all(['nav', 'div', 'ul'], 
        class_=lambda x: x and any(term in str(x).lower() for term in 
            ['pager', 'pagination', 'page-nav', 'pages']))
    
    # Also look for links that look like page numbers
    all_links = soup.find_all('a', href=True)
    
    for link in all_links:
        href = link.get('href', '')
        text = link.get_text(strip=True)
        
        # Skip empty or javascript links
        if not href or href.startswith(('javascript:', '#', 'mailto:')):
            continue
        
        # Check if this looks like a pagination link
        is_pagination = False
        
        # Pattern 1: Link text is a number (1, 2, 3...)
        if text.isdigit() and int(text) <= 50:
            is_pagination = True
        
        # Pattern 2: URL contains page= or /page/
        if re.search(r'[?&]page=\d+', href) or re.search(r'/page/\d+', href):
            is_pagination = True
        
        # Pattern 3: "Next" or arrow links
        if text.lower() in ['next', 'next »', '→', '>>', 'next page']:
            is_pagination = True
        
        if is_pagination:
            full_url = urljoin(base_url, href)
            if full_url not in seen_urls:
                page_urls.append(full_url)
                seen_urls.add(full_url)
    
    # Sort by page number if possible
    def extract_page_num(url):
        match = re.search(r'page[=/](\d+)', url)
        if match:
            return int(match.group(1))
        return 0
    
    page_urls.sort(key=extract_page_num)
    
    return page_urls




def scrape_contacts(url: str, deep_scrape: bool = True, max_profiles: int = 100, progress_callback=None) -> list[dict]:
    """
    Scrape public academic contacts from a webpage.
    
    Args:
        url: The webpage URL to scrape
        deep_scrape: If True, follow profile links to find emails
        max_profiles: Maximum number of profile pages to visit (default 100, max 1000)
        progress_callback: Optional callback(current, total, message) for progress updates
        
    Returns:
        List of dicts with 'name', 'email', 'source' keys
        
    Raises:
        ScraperError: If scraping fails
    """
    max_profiles = min(max_profiles, 1000)  # Cap at 1000
    
    # Validate URL
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ScraperError("Invalid URL format. Please include http:// or https://")
    
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    # Fetch the main page
    try:
        if progress_callback:
            progress_callback(0, 1, "Fetching main page...")
        response = fetch_page(url, timeout=Config.SCRAPE_TIMEOUT)
    except requests.Timeout:
        raise ScraperError(f"Request timed out after {Config.SCRAPE_TIMEOUT} seconds.")
    except requests.exceptions.ConnectionError:
        raise ScraperError("Could not connect to the website. Please check the URL and your internet connection.")
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            raise ScraperError("Page not found (404). Please check the URL is correct.")
        elif e.response.status_code == 403:
            raise ScraperError("Access forbidden (403). The website may be blocking automated requests.")
        else:
            raise ScraperError(f"HTTP error {e.response.status_code}: {str(e)}")
    except requests.RequestException as e:
        raise ScraperError(f"Failed to fetch page: {str(e)}")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    contacts = []
    seen_emails = set()
    
    # Phase 1: Try to find emails on the main page
    if progress_callback:
        progress_callback(0, 1, "Scanning main page for emails...")
    
    main_page_contacts = extract_contacts_from_soup(soup, url, seen_emails)
    contacts.extend(main_page_contacts)
    
    # Phase 2: If no emails found and deep_scrape is enabled, find profile links
    if deep_scrape and len(contacts) == 0:
        if progress_callback:
            progress_callback(0, 1, "No emails on main page. Finding profile links...")
        
        profile_links = find_profile_links(soup, base_url, url)
        
        if profile_links:
            total_profiles = min(len(profile_links), max_profiles)
            if progress_callback:
                progress_callback(0, total_profiles, f"Found {len(profile_links)} profiles. Scanning up to {total_profiles}...")
            
            # Scrape profile pages (with rate limiting)
            for idx, (name, profile_url) in enumerate(profile_links[:max_profiles]):
                if progress_callback:
                    progress_callback(idx + 1, total_profiles, f"Scanning profile {idx + 1}/{total_profiles}: {name}")
                
                try:
                    profile_contacts = scrape_profile_page(profile_url, name, seen_emails)
                    contacts.extend(profile_contacts)
                    
                    # Small delay to be respectful
                    if idx < total_profiles - 1:
                        time.sleep(0.3)
                        
                except Exception as e:
                    # Skip failed profile pages
                    continue
    
    return contacts


def extract_contacts_from_soup(soup: BeautifulSoup, source_url: str, seen_emails: set) -> list[dict]:
    """Extract contacts from a BeautifulSoup object."""
    contacts = []
    
    # Method 1: Find mailto links
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if href.startswith('mailto:'):
            email = extract_email_from_mailto(href)
            if email and is_valid_academic_email(email) and email not in seen_emails:
                name = extract_name_near_link(link)
                contacts.append({
                    'name': name,
                    'email': email,
                    'source': source_url
                })
                seen_emails.add(email)
    
    # Method 2: Regex search in page text
    page_text = soup.get_text()
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    
    for match in re.finditer(email_pattern, page_text):
        email = match.group().lower()
        if is_valid_academic_email(email) and email not in seen_emails:
            name = extract_name_near_text(page_text, match.start())
            contacts.append({
                'name': name,
                'email': email,
                'source': source_url
            })
            seen_emails.add(email)
    
    return contacts


def find_profile_links(soup: BeautifulSoup, base_url: str, page_url: str) -> list[tuple[str, str]]:
    """
    Find links to individual profile pages.
    Returns list of (name, url) tuples in page order.
    """
    profile_links = []
    seen_urls = set()
    
    # Method 1: Find links that look like profile URLs and extract name from link text
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        
        # Skip non-profile links
        if not looks_like_profile_url(href, page_url):
            continue
        
        full_url = urljoin(base_url, href)
        if full_url in seen_urls:
            continue
        
        # Try to get name from link text first (most reliable)
        link_text = link.get_text(strip=True)
        if link_text and looks_like_name(link_text):
            profile_links.append((clean_name(link_text), full_url))
            seen_urls.add(full_url)
            continue
        
        # If link text isn't a name, look for name in nearby elements
        name = None
        
        # Check parent container for a name
        parent = link.parent
        if parent:
            # Look for heading or strong text nearby
            for elem in parent.find_all(['h2', 'h3', 'h4', 'h5', 'strong', 'b', 'span']):
                text = elem.get_text(strip=True)
                if text and looks_like_name(text) and text != link_text:
                    name = clean_name(text)
                    break
            
            # Check grandparent too
            if not name and parent.parent:
                for elem in parent.parent.find_all(['h2', 'h3', 'h4', 'h5', 'strong', 'b']):
                    text = elem.get_text(strip=True)
                    if text and looks_like_name(text):
                        name = clean_name(text)
                        break
        
        # Also try extracting name from URL (e.g., /people/john-smith -> John Smith)
        if not name:
            name = extract_name_from_url(href)
        
        if name and name != "Unknown":
            profile_links.append((name, full_url))
            seen_urls.add(full_url)
    
    return profile_links


def extract_name_from_url(url: str) -> str:
    """Try to extract a person's name from a profile URL."""
    # Common patterns: /people/john-smith, /faculty/jane-doe, /profile/firstname-lastname
    import re
    
    match = re.search(r'/(?:people|person|faculty|staff|profile|user|~)/([\w-]+)/?$', url.lower())
    if match:
        slug = match.group(1)
        # Convert slug to name: john-smith -> John Smith
        parts = slug.replace('_', '-').split('-')
        if len(parts) >= 2 and all(len(p) >= 2 for p in parts):
            name = ' '.join(part.capitalize() for part in parts)
            if looks_like_name(name):
                return name
    
    return "Unknown"




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
    
    # Also accept relative URLs that look like names or IDs
    if re.match(r'^[a-z0-9\-_]+/?$', href_lower):
        return True
    
    return False


def scrape_profile_page(url: str, known_name: str, seen_emails: set) -> list[dict]:
    """Scrape a single profile page for email."""
    contacts = []
    
    try:
        response = fetch_page(url, timeout=8)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for emails
        page_text = soup.get_text()
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        
        for match in re.finditer(email_pattern, page_text):
            email = match.group().lower()
            if is_valid_academic_email(email) and email not in seen_emails:
                # Use the known name from the listing page
                contacts.append({
                    'name': known_name if known_name != "Unknown" else extract_name_near_text(page_text, match.start()),
                    'email': email,
                    'source': url
                })
                seen_emails.add(email)
                break  # Usually one email per person is enough
        
        # Also check mailto links
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if href.startswith('mailto:'):
                email = extract_email_from_mailto(href)
                if email and is_valid_academic_email(email) and email not in seen_emails:
                    contacts.append({
                        'name': known_name if known_name != "Unknown" else extract_name_near_link(link),
                        'email': email,
                        'source': url
                    })
                    seen_emails.add(email)
                    break
                    
    except Exception:
        pass  # Skip failed pages silently
    
    return contacts


def extract_email_from_mailto(href: str) -> Optional[str]:
    """Extract email address from a mailto: link."""
    email = href.replace('mailto:', '').split('?')[0].strip().lower()
    if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return email
    return None


def extract_name_near_link(link_element) -> str:
    """Try to extract a name from the context around a mailto link."""
    # Check link text itself (if it's not the email)
    link_text = link_element.get_text(strip=True)
    if link_text and '@' not in link_text and looks_like_name(link_text):
        return clean_name(link_text)
    
    # Look for previous headings (most common pattern for faculty pages)
    for heading_tag in ['h2', 'h3', 'h4', 'h1', 'strong', 'b']:
        prev = link_element.find_previous(heading_tag)
        if prev:
            text = prev.get_text(strip=True)
            if text and looks_like_name(text):
                return clean_name(text)
    
    # Check parent and grandparent for text content
    for ancestor in [link_element.parent, link_element.parent.parent if link_element.parent else None]:
        if ancestor:
            for child in ancestor.children:
                if hasattr(child, 'name') and child.name in ['h2', 'h3', 'h4', 'strong', 'b']:
                    text = child.get_text(strip=True)
                    if text and looks_like_name(text):
                        return clean_name(text)
    
    # Check parent's previous sibling for a heading
    if link_element.parent:
        parent = link_element.parent
        prev_sibling = parent.find_previous_sibling()
        if prev_sibling:
            text = prev_sibling.get_text(strip=True)
            if text and looks_like_name(text):
                return clean_name(text)
    
    return "Unknown"


def extract_name_near_text(full_text: str, email_pos: int) -> str:
    """Try to extract a name from text near an email position."""
    start = max(0, email_pos - 100)
    context = full_text[start:email_pos]
    
    words = context.split()
    name_candidates = []
    for word in reversed(words[-6:]):
        clean = re.sub(r'[^\w\s]', '', word).strip()
        if clean and clean[0].isupper() and len(clean) > 1:
            name_candidates.insert(0, clean)
            if len(name_candidates) >= 2:
                break
    
    if name_candidates:
        return ' '.join(name_candidates)
    
    return "Unknown"


def clean_name(name: str) -> str:
    """Clean up a name string."""
    # Remove common titles and suffixes
    name = re.sub(r'\b(Dr\.?|Prof\.?|Professor|PhD|Ph\.D\.?|Mr\.?|Ms\.?|Mrs\.?)\b', '', name, flags=re.IGNORECASE)
    # Remove extra whitespace
    name = ' '.join(name.split())
    return name.strip() or "Unknown"


def looks_like_name(text: str) -> bool:
    """Check if text looks like a person's name."""
    if not text or len(text) < 3 or len(text) > 60:
        return False
    
    # Should have at least some letters
    if not any(c.isalpha() for c in text):
        return False
    
    # Should not be all uppercase (likely a header)
    if text.isupper() and len(text) > 20:
        return False
    
    text_lower = text.lower().strip()
    
    # Filter out common navigation/section phrases (NOT names)
    # These can be single words or multi-word phrases
    navigation_patterns = [
        # Single words that are never names
        'students', 'faculty', 'staff', 'people', 'members', 'team',
        'directory', 'all', 'next', 'previous', 'back', 'home', 'about',
        'research', 'publications', 'news', 'events', 'alumni', 'overview',
        'administration', 'leadership', 'department', 'lecturers', 'adjunct',
        # Multi-word phrases
        'view all', 'show all', 'load more', 'see more', 'read more',
        'phd students', 'masters students', 'graduate students', 
        'undergraduate students', 'postdoctoral fellows', 'postdocs',
        'courtesy faculty', 'adjunct faculty', 'visiting faculty',
        'research staff', 'administrative staff', 'in memoriam',
        'affiliated faculty', 'emeritus faculty', 'primary faculty',
        'core faculty', 'joint faculty', 'associated faculty'
    ]
    
    # Check exact match first (single word navigations)
    if text_lower in navigation_patterns:
        return False
    
    # Check if any navigation phrase is contained in the text
    for pattern in navigation_patterns:
        if pattern in text_lower:
            return False
    
    # Should not contain obvious non-name patterns
    non_name_patterns = ['@', 'http', 'www', '.edu', '.com', 'email', 'phone', 
                         'contact', 'address', 'office', 'building', 'room',
                         'click', 'view', 'more', 'see all', 'read', 'download',
                         'page', 'next', 'prev', 'load']
    if any(pattern in text_lower for pattern in non_name_patterns):
        return False
    
    # Should start with a capital letter
    if text[0].islower():
        return False
    
    # Should have at least two words (first and last name) or be a plausible single name
    words = text.split()
    if len(words) >= 2:
        # Check that words look like name parts (not numbers or weird strings)
        if all(word[0].isupper() or word.lower() in ['de', 'van', 'von', 'la', 'le', 'del'] for word in words if word):
            return True
    elif len(words) == 1 and len(text) >= 4:
        return True
    
    return False


def is_valid_academic_email(email: str) -> bool:
    """Check if email looks like a valid academic email (not a system/generic email)."""
    email = email.lower()
    
    # Filter out common system/generic emails
    invalid_patterns = [
        'noreply', 'no-reply', 'donotreply', 'admin@', 'info@', 'contact@',
        'support@', 'help@', 'webmaster', 'postmaster', 'mailer-daemon',
        'newsletter', 'notifications', 'alerts@', 'system@', 'automated',
        'example.com', 'test.com', 'localhost', 'mailinator', 'tempmail',
        'office@', 'department@', 'general@', 'enquiries@', 'admissions@'
    ]
    
    if any(pattern in email for pattern in invalid_patterns):
        return False
    
    # Should have academic domain or at least look personal
    # Personal emails usually have name patterns like firstname.lastname@ or initials
    local_part = email.split('@')[0]
    
    # Very short local parts are often generic
    if len(local_part) < 3:
        return False
    
    return True
