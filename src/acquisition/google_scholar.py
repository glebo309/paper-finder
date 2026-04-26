#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Scholar PDF extraction - ENHANCED VERSION

Comprehensive Google Scholar scraper with:
- Multiple search strategies (title, DOI, author+title, fuzzy)
- Intelligent rate limiting with exponential backoff
- CAPTCHA detection and graceful degradation
- Rotating user agents
- "All versions" link parsing for OA copies
- Institutional repository extraction
- Fuzzy title matching
- Smart timeout controls
- Retry logic with circuit breaker
"""

import re
import time
import random
import hashlib
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Set
from urllib.parse import quote, urljoin, urlparse, parse_qs
from difflib import SequenceMatcher
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup


# ============================================================================
# CONFIGURATION
# ============================================================================

# Rotating user agents to avoid detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]

# Rate limiting configuration
MIN_DELAY = 3.0  # Minimum delay between requests (seconds)
MAX_DELAY = 8.0  # Maximum delay between requests (seconds)
BACKOFF_FACTOR = 2.0  # Exponential backoff multiplier
MAX_RETRIES = 3  # Maximum retry attempts per request
CAPTCHA_COOLDOWN = 300  # Cooldown period after CAPTCHA detection (seconds)

# Search configuration
MAX_RESULTS_PER_QUERY = 10  # Maximum results to parse per query
MAX_TOTAL_CANDIDATES = 30  # Maximum total PDF candidates to try
TITLE_SIMILARITY_THRESHOLD = 0.5  # Minimum similarity for fuzzy title matching
MIN_PDF_SIZE = 50 * 1024  # Minimum PDF size (50 KB)
MAX_PDF_SIZE = 500 * 1024 * 1024  # Maximum PDF size (500 MB)
REQUEST_TIMEOUT = 30  # Request timeout (seconds)

# Circuit breaker state
_captcha_detected_at: Optional[datetime] = None
_consecutive_failures = 0
MAX_CONSECUTIVE_FAILURES = 5


@dataclass
class PDFCandidate:
    """Represents a potential PDF source"""
    url: str
    source_type: str
    priority: int
    description: str
    requires_extraction: bool = False  # True if URL is a page, not direct PDF
    
    def __hash__(self):
        return hash(self.url)
    
    def __eq__(self, other):
        return isinstance(other, PDFCandidate) and self.url == other.url


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _get_random_user_agent() -> str:
    """Get a random user agent from the pool"""
    return random.choice(USER_AGENTS)


def _check_circuit_breaker() -> bool:
    """Check if circuit breaker is open (too many failures)"""
    global _captcha_detected_at, _consecutive_failures
    
    # Check CAPTCHA cooldown
    if _captcha_detected_at:
        elapsed = (datetime.now() - _captcha_detected_at).total_seconds()
        if elapsed < CAPTCHA_COOLDOWN:
            print(f"  ⚠ CAPTCHA cooldown active ({int(CAPTCHA_COOLDOWN - elapsed)}s remaining)")
            return False
        else:
            # Reset after cooldown
            _captcha_detected_at = None
            _consecutive_failures = 0
    
    # Check consecutive failures
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        print(f"  ⚠ Too many consecutive failures ({_consecutive_failures}), circuit breaker open")
        return False
    
    return True


def _mark_success():
    """Mark a successful request"""
    global _consecutive_failures
    _consecutive_failures = 0


def _mark_failure():
    """Mark a failed request"""
    global _consecutive_failures
    _consecutive_failures += 1


def _detect_captcha(response: requests.Response) -> bool:
    """Detect if response contains a CAPTCHA challenge"""
    global _captcha_detected_at
    
    # Check status code
    if response.status_code == 429:  # Too Many Requests
        _captcha_detected_at = datetime.now()
        return True
    
    # Check content
    content_lower = response.text.lower()
    captcha_indicators = [
        'captcha',
        'unusual traffic',
        'automated requests',
        'verify you are human',
        'recaptcha',
        'security check',
    ]
    
    for indicator in captcha_indicators:
        if indicator in content_lower:
            _captcha_detected_at = datetime.now()
            print(f"  ⚠ CAPTCHA detected: '{indicator}'")
            return True
    
    return False


def _calculate_title_similarity(title1: str, title2: str) -> float:
    """Calculate similarity between two titles (0.0 to 1.0)"""
    if not title1 or not title2:
        return 0.0
    
    # Normalize
    t1 = re.sub(r'[^a-z0-9\s]', '', title1.lower())
    t2 = re.sub(r'[^a-z0-9\s]', '', title2.lower())
    
    # Sequence matcher
    return SequenceMatcher(None, t1, t2).ratio()


def _is_university_domain(url: str) -> bool:
    """Check if URL is from a university or institutional repository"""
    if not url:
        return False
    
    url_lower = url.lower()
    
    # University domains (expanded list)
    university_tlds = [
        '.edu', '.ac.uk', '.ac.cn', '.edu.cn', '.ac.jp', '.edu.au',
        '.ac.in', '.edu.br', '.ac.za', '.edu.sg', '.ac.kr', '.edu.tw',
        '.ac.nz', '.edu.hk', '.ac.il', '.edu.mx', '.ac.at', '.edu.ar',
        '.ac.th', '.edu.my', '.ac.id', '.edu.ph', '.ac.ae', '.edu.sa',
        '.ac.eg', '.edu.pk', '.ac.ir', '.edu.vn', '.ac.lk', '.edu.bd',
    ]
    
    for tld in university_tlds:
        if tld in url_lower:
            return True
    
    # Known institutional repositories (expanded)
    repo_domains = [
        'arxiv.org', 'biorxiv.org', 'medrxiv.org', 'chemrxiv.org',
        'ssrn.com', 'researchgate.net', 'academia.edu', 'philpapers.org',
        'hal.archives-ouvertes.fr', 'zenodo.org', 'figshare.com',
        'osf.io', 'europepmc.org', 'ncbi.nlm.nih.gov/pmc',
        'scielo', 'redalyc.org', 'dialnet.unirioja.es',
        'repository', 'dspace', 'eprints', 'scholarworks',
        'digitalcommons', 'handle.net', 'pure.', 'research-repository',
    ]
    
    for domain in repo_domains:
        if domain in url_lower:
            return True
    
    return False


def _is_pdf_link(url: str, link_text: str = "") -> bool:
    """Check if URL likely points to a PDF"""
    if not url:
        return False
    
    url_lower = url.lower()
    text_lower = link_text.lower()
    
    # Direct PDF URL
    if url_lower.endswith('.pdf'):
        return True
    
    # PDF in URL path
    if '/pdf' in url_lower or 'pdf/' in url_lower:
        return True
    
    # Link text indicates PDF
    if any(word in text_lower for word in ['pdf', 'download', 'full text', 'view pdf']):
        return True
    
    return False


def search_google_scholar(
    title: str,
    doi: str = None,
    author: str = None,
    year: str = None,
    max_results: int = MAX_RESULTS_PER_QUERY
) -> List[PDFCandidate]:
    """
    Search Google Scholar with multiple strategies and extract PDF candidates.
    
    Strategies:
    1. Exact title match
    2. DOI search (if provided)
    3. Title + author
    4. "All versions" link parsing for OA copies
    
    Returns list of PDFCandidate objects, sorted by priority.
    """
    if not title:
        return []
    
    # Check circuit breaker
    if not _check_circuit_breaker():
        return []
    
    candidates: Set[PDFCandidate] = set()
    
    # Strategy 1: Exact title search
    print("  Strategy 1: Exact title search")
    candidates.update(_search_scholar_query(f'"{title}"', title, max_results))
    
    # Strategy 2: DOI search (if provided)
    if doi and len(candidates) < max_results:
        print("  Strategy 2: DOI search")
        candidates.update(_search_scholar_query(doi, title, max_results))
    
    # Strategy 3: Title + author (if provided)
    if author and len(candidates) < max_results:
        print("  Strategy 3: Title + author search")
        query = f'"{title}" author:"{author}"'
        candidates.update(_search_scholar_query(query, title, max_results))
    
    # Strategy 4: Fuzzy title search (first few words)
    if len(candidates) < max_results:
        print("  Strategy 4: Fuzzy title search")
        # Use first 5-7 words for broader search
        words = title.split()[:7]
        fuzzy_query = ' '.join(words)
        candidates.update(_search_scholar_query(fuzzy_query, title, max_results))
    
    # Convert to list and sort by priority
    result_list = sorted(list(candidates), key=lambda x: x.priority, reverse=True)
    
    print(f"  Found {len(result_list)} unique candidates")
    return result_list[:MAX_TOTAL_CANDIDATES]


def _search_scholar_query(
    query: str,
    expected_title: str,
    max_results: int
) -> Set[PDFCandidate]:
    """
    Execute a single Google Scholar search query and extract candidates.
    
    Returns set of PDFCandidate objects.
    """
    candidates: Set[PDFCandidate] = set()
    
    try:
        # Build request
        base_url = "https://scholar.google.com/scholar"
        params = {
            'q': query,
            'hl': 'en',
            'as_sdt': '0,5',  # Search all articles
            'num': max_results,
        }
        
        headers = {
            'User-Agent': _get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Smart delay with jitter
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        time.sleep(delay)
        
        # Make request with retry logic
        response = None
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(
                    base_url,
                    params=params,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True
                )
                break
            except requests.exceptions.Timeout:
                if attempt < MAX_RETRIES - 1:
                    backoff = BACKOFF_FACTOR ** attempt
                    print(f"    Timeout, retrying in {backoff}s...")
                    time.sleep(backoff)
                else:
                    print("    Max retries reached")
                    _mark_failure()
                    return candidates
            except Exception as e:
                print(f"    Request error: {type(e).__name__}")
                _mark_failure()
                return candidates
        
        if not response or response.status_code != 200:
            status = response.status_code if response else 'Connection Failed'
            # Only print if not just a 404/empty result (which are common)
            if status != 404:
                print(f"    Scholar query failed: {status}")
            _mark_failure()
            return candidates
        
        # Check for CAPTCHA
        if _detect_captcha(response):
            _mark_failure()
            return candidates
        
        # Success!
        _mark_success()
        
        # Parse results
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all result divs (updated selectors for current Scholar layout)
        result_divs = soup.find_all('div', class_='gs_r') or soup.find_all('div', class_='gs_ri')
        
        for result_div in result_divs[:max_results]:
            # Extract title for similarity check
            title_elem = result_div.find('h3', class_='gs_rt') or result_div.find('a')
            result_title = title_elem.get_text().strip() if title_elem else ""
            
            # Check title similarity
            similarity = _calculate_title_similarity(expected_title, result_title)
            if similarity < TITLE_SIMILARITY_THRESHOLD:
                continue  # Skip low-similarity results
            
            # 1. Check for direct PDF link (right sidebar)
            pdf_link_div = result_div.find('div', class_='gs_or_ggsm') or result_div.find('div', class_='gs_ggsd')
            if pdf_link_div:
                link_elem = pdf_link_div.find('a', href=True)
                if link_elem:
                    pdf_url = link_elem['href']
                    source_type, priority = _classify_pdf_source(pdf_url)
                    description = link_elem.get_text().strip() or "Direct PDF"
                    
                    candidates.add(PDFCandidate(
                        url=pdf_url,
                        source_type=source_type,
                        priority=priority + int(similarity * 5),  # Boost by similarity
                        description=description,
                        requires_extraction=not pdf_url.lower().endswith('.pdf')
                    ))
            
            # 2. Check for "All X versions" link (often has OA copies)
            versions_link = result_div.find('a', string=re.compile(r'All \d+ versions?', re.I))
            if versions_link and versions_link.get('href'):
                versions_url = urljoin(base_url, versions_link['href'])
                # Parse versions page for OA links
                version_candidates = _parse_versions_page(versions_url, expected_title)
                candidates.update(version_candidates)
            
            # 3. Check main result link (might be institutional repository)
            main_link = result_div.find('h3', class_='gs_rt')
            if main_link:
                link_elem = main_link.find('a', href=True)
                if link_elem:
                    page_url = link_elem['href']
                    if _is_university_domain(page_url):
                        source_type, priority = _classify_pdf_source(page_url)
                        candidates.add(PDFCandidate(
                            url=page_url,
                            source_type=source_type,
                            priority=priority + int(similarity * 5),
                            description=f"Institutional page: {result_title[:50]}",
                            requires_extraction=True
                        ))
    
    except Exception as e:
        print(f"    Search query failed: {type(e).__name__}: {e}")
        _mark_failure()
    
    return candidates


def _parse_versions_page(versions_url: str, expected_title: str) -> Set[PDFCandidate]:
    """
    Parse the "All versions" page to find Open Access copies.
    
    Returns set of PDFCandidate objects.
    """
    candidates: Set[PDFCandidate] = set()
    
    try:
        headers = {'User-Agent': _get_random_user_agent()}
        time.sleep(random.uniform(2, 4))  # Be polite
        
        response = requests.get(versions_url, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200 or _detect_captcha(response):
            return candidates
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all version entries
        for result_div in soup.find_all('div', class_='gs_r')[:5]:  # Check top 5 versions
            # Look for PDF links
            pdf_link_div = result_div.find('div', class_='gs_or_ggsm')
            if pdf_link_div:
                link_elem = pdf_link_div.find('a', href=True)
                if link_elem:
                    pdf_url = link_elem['href']
                    source_type, priority = _classify_pdf_source(pdf_url)
                    
                    candidates.add(PDFCandidate(
                        url=pdf_url,
                        source_type=source_type,
                        priority=priority + 2,  # Boost versions page results
                        description=f"Version: {link_elem.get_text().strip()}",
                        requires_extraction=not pdf_url.lower().endswith('.pdf')
                    ))
    
    except Exception:
        pass  # Silent fail for versions page
    
    return candidates


def _classify_pdf_source(url: str) -> Tuple[str, int]:
    """
    Classify PDF source and assign a quality score.
    
    Returns (source_type, score)
    """
    url_lower = url.lower()
    
    # Universities (highest trust)
    if any(domain in url_lower for domain in ['.edu', '.ac.uk', '.ac.cn', '.edu.cn', 
                                                '.edu.au', '.ac.jp', '.edu.br', '.ac.in']):
        return 'university', 10
    
    # Institutional repositories
    if any(repo in url_lower for repo in ['repository', 'dspace', 'eprints', 'archive']):
        return 'repository', 9
    
    # Known academic sites
    if 'arxiv.org' in url_lower:
        return 'arxiv', 10
    elif 'biorxiv.org' in url_lower or 'medrxiv.org' in url_lower:
        return 'preprint', 9
    elif 'researchgate.net' in url_lower:
        return 'researchgate', 6
    elif 'academia.edu' in url_lower:
        return 'academia', 5
    elif 'ssrn.com' in url_lower:
        return 'ssrn', 8
    elif 'philpapers.org' in url_lower:
        return 'philpapers', 8
    elif 'zenodo.org' in url_lower:
        return 'zenodo', 8
    elif 'figshare.com' in url_lower:
        return 'figshare', 7
    elif 'osf.io' in url_lower:
        return 'osf', 7
    elif 'hal.' in url_lower:
        return 'hal', 9
    elif 'scielo' in url_lower:
        return 'scielo', 9
    elif 'cyberleninka' in url_lower:
        return 'cyberleninka', 8
    
    # Generic but promising
    elif any(domain in url_lower for domain in ['.org', '.gov']):
        return 'organization', 4
    
    # Unknown but has PDF indicators
    elif '.pdf' in url_lower:
        return 'direct_pdf', 3
    
    return 'unknown', 1


def _get_source_priority(source_type: str) -> int:
    """
    Get priority score for sorting results.
    """
    priorities = {
        'university': 10,
        'arxiv': 10,
        'repository': 9,
        'preprint': 9,
        'hal': 9,
        'scielo': 9,
        'cyberleninka': 8,
        'ssrn': 8,
        'philpapers': 8,
        'zenodo': 8,
        'figshare': 7,
        'osf': 7,
        'researchgate': 6,
        'academia': 5,
        'organization': 4,
        'direct_pdf': 3,
        'unknown': 1,
    }
    return priorities.get(source_type, 0)


def extract_pdf_from_page(page_url: str, expected_title: str = None) -> Optional[str]:
    """
    Visit a page and try to extract PDF link.
    
    Common patterns:
    - Direct PDF link in page
    - Download button
    - View PDF button
    """
    if not page_url:
        return None
    
    try:
        headers = {'User-Agent': UA}
        response = requests.get(page_url, headers=headers, timeout=15, allow_redirects=True)
        
        if response.status_code != 200:
            return None
        
        # Check if response is already a PDF
        if response.headers.get('content-type', '').lower().startswith('application/pdf'):
            return page_url
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for PDF links
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().strip()
            
            if _is_pdf_link(href, text):
                # Make absolute URL
                pdf_url = urljoin(page_url, href)
                return pdf_url
        
        # Look for meta tags with PDF URLs
        for meta in soup.find_all('meta'):
            if meta.get('name') == 'citation_pdf_url' or meta.get('property') == 'citation_pdf_url':
                pdf_url = meta.get('content')
                if pdf_url:
                    return urljoin(page_url, pdf_url)
        
    except Exception as e:
        pass
    
    return None


def try_fetch_from_google_scholar(
    title: str,
    doi: str,
    outpath: Path,
    author: str = None,
    year: str = None,
    validate_title: bool = True
) -> Optional[str]:
    """
    Try to fetch PDF via Google Scholar - ENHANCED VERSION.
    
    Uses multiple search strategies, intelligent rate limiting,
    and comprehensive result parsing.
    
    Returns source type if successful, None otherwise.
    """
    if not title:
        return None
    
    print("  Searching Google Scholar (enhanced)...")
    
    # Search Google Scholar with all strategies
    candidates = search_google_scholar(title, doi, author, year)
    
    if not candidates:
        print("    No Google Scholar results found")
        return None
    
    print(f"  Found {len(candidates)} candidates (sorted by priority)")
    
    # Create session with rotating user agent
    session = requests.Session()
    session.headers.update({'User-Agent': _get_random_user_agent()})
    
    # Try each candidate in priority order
    for i, candidate in enumerate(candidates, 1):
        try:
            print(f"  [{i}/{len(candidates)}] Trying {candidate.source_type} (priority {candidate.priority}): {candidate.url[:70]}...")
            
            # If it requires extraction (page, not direct PDF), extract first
            if candidate.requires_extraction:
                pdf_url = extract_pdf_from_page(candidate.url, title)
                if not pdf_url:
                    print(f"    ✗ No PDF found on page")
                    continue
            else:
                pdf_url = candidate.url
            
            # Download the PDF
            response = session.get(
                pdf_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
                stream=True
            )
            
            # Check status
            if response.status_code != 200:
                print(f"    ✗ HTTP {response.status_code}")
                continue
            
            # Check content type
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' not in content_type and 'octet-stream' not in content_type:
                print(f"    ✗ Not a PDF (content-type: {content_type})")
                continue
            
            # Download content
            content = b''
            for chunk in response.iter_content(chunk_size=1024*1024):
                if chunk:
                    content += chunk
                    # Check size limit
                    if len(content) > MAX_PDF_SIZE:
                        print(f"    ✗ File too large (>{MAX_PDF_SIZE/1024/1024:.0f} MB)")
                        break
            
            # Validate PDF
            if len(content) < MIN_PDF_SIZE:
                print(f"    ✗ File too small (<{MIN_PDF_SIZE/1024:.0f} KB)")
                continue
            
            if content[:4] != b'%PDF':
                print(f"    ✗ Not a valid PDF (magic bytes)")
                continue
            
            # Save
            with outpath.open('wb') as f:
                f.write(content)
            
            print(f"  ✓ Downloaded from {candidate.source_type} ({len(content)/1024/1024:.2f} MB)")
            return candidate.source_type
            
        except requests.exceptions.Timeout:
            print(f"    ✗ Timeout")
            continue
        except Exception as e:
            print(f"    ✗ Failed: {type(e).__name__}")
            continue
        finally:
            # Small delay between attempts
            if i < len(candidates):
                time.sleep(random.uniform(1, 2))
    
    print("  All candidates exhausted")
    return None


# ============================================================================
# RESEARCHGATE
# ============================================================================

def search_researchgate(title: str, author: str = None) -> List[str]:
    """
    Search ResearchGate for PDFs.
    
    Note: ResearchGate requires login for most PDFs, so this has limited success.
    """
    if not title:
        return []
    
    candidates = []
    
    try:
        base_url = "https://www.researchgate.net/search/publication"
        params = {'q': title}
        
        headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        
        time.sleep(random.uniform(2, 3))
        
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for publication links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/publication/' in href and 'researchgate.net' in href:
                candidates.append(href)
        
    except Exception as e:
        pass
    
    return candidates[:5]  # Return top 5


# ============================================================================
# ACADEMIA.EDU
# ============================================================================

def search_academia_edu(title: str, author: str = None) -> List[str]:
    """
    Search Academia.edu for PDFs.
    
    Note: Academia.edu also requires login for most PDFs.
    """
    if not title:
        return []
    
    candidates = []
    
    try:
        # Academia.edu search
        base_url = "https://www.academia.edu/search"
        params = {'q': title}
        
        headers = {'User-Agent': UA}
        
        time.sleep(random.uniform(2, 3))
        
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for paper links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if 'academia.edu' in href and '/attachments/' not in href:
                candidates.append(href)
        
    except Exception as e:
        pass
    
    return candidates[:5]


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    # Test Google Scholar search
    test_title = "Attention Is All You Need"
    
    print("=" * 80)
    print(f"Testing Google Scholar search for: {test_title}")
    print("=" * 80)
    print()
    
    results = search_google_scholar(test_title)
    
    print(f"Found {len(results)} results:")
    for source_type, url, desc in results:
        print(f"  {source_type}: {url[:80]}...")
        print(f"    Description: {desc}")
        print()
