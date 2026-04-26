#!/usr/bin/env python3
"""
Anna's Archive integration - The ULTIMATE source for books and papers.

Anna's Archive aggregates:
- LibGen (papers + books)
- Z-Library (books)
- Sci-Hub (papers)
- ISBNdb (metadata)
- OpenLibrary (books)

Coverage: 100M+ books, 80M+ papers
This is the SINGLE BEST source for book chapters and proceedings.
"""

import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Optional, List, Dict
import time
import hashlib
import logging

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Anna's Archive mirrors - they frequently change domains
# Updated list with working mirrors as of 2026
ANNAS_MIRRORS = [
    "https://annas-archive.pm",   # Primary working mirror
    "https://annas-archive.li",   # Working mirror
    "https://annas-archive.in",   # Working mirror
    "https://annas-archive.gs",   # Alternative
    "https://annas-archive.org",  # Original (may be down)
    "https://annas-archive.se",   # Alternative (may be down)
]

# Cache for domain availability (domain -> (is_available, timestamp))
_DOMAIN_CACHE = {}
_CACHE_DURATION = 300  # 5 minutes

def _check_domain_available(domain: str, timeout: int = 5) -> bool:
    """
    Check if a domain is available and responding.
    Uses caching to avoid repeated checks.
    
    Args:
        domain: Full URL like 'https://annas-archive.pm'
        timeout: Connection timeout in seconds
    
    Returns:
        True if domain is available, False otherwise
    """
    current_time = time.time()
    
    # Check cache first
    if domain in _DOMAIN_CACHE:
        is_available, cached_time = _DOMAIN_CACHE[domain]
        if current_time - cached_time < _CACHE_DURATION:
            return is_available
    
    # Test domain availability
    try:
        response = requests.head(
            domain,
            headers={'User-Agent': UA},
            timeout=timeout,
            allow_redirects=True
        )
        is_available = response.status_code < 500
        _DOMAIN_CACHE[domain] = (is_available, current_time)
        return is_available
    except Exception as e:
        logger.debug(f"Domain check failed for {domain}: {type(e).__name__}")
        _DOMAIN_CACHE[domain] = (False, current_time)
        return False

def _get_working_mirrors() -> List[str]:
    """
    Get list of working mirrors, checking availability.
    Returns mirrors in priority order with working ones first.
    """
    working = []
    failed = []
    
    for mirror in ANNAS_MIRRORS:
        if _check_domain_available(mirror):
            working.append(mirror)
        else:
            failed.append(mirror)
    
    # Return working mirrors first, then failed ones as fallback
    return working + failed


def search_annas_archive(query: str, search_type: str = "title") -> List[Dict]:
    """
    Search Anna's Archive.
    
    Args:
        query: DOI, title, or ISBN
        search_type: 'doi', 'title', or 'isbn'
    """
    results = []
    
    # Get working mirrors (prioritizes available domains)
    mirrors = _get_working_mirrors()
    
    for mirror in mirrors:
        try:
            # Anna's Archive search
            search_url = f"{mirror}/search"
            params = {'q': query}
            
            headers = {
                'User-Agent': UA,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
            
            response = requests.get(search_url, params=params, headers=headers, timeout=15)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Parse search results - try multiple selectors (Anna's changes HTML often)
                # Try: main result links
                for item in soup.select('a[href*="/md5/"]')[:10]:
                    # Skip navigation/footer links
                    if 'md5' in item.get('href', ''):
                        title_text = item.get_text().strip()
                        if len(title_text) > 10:  # Real titles are longer
                            result = {
                                'url': mirror + item['href'] if item['href'].startswith('/') else item['href'],
                                'title': title_text
                            }
                            if result not in results:
                                results.append(result)
                
                if results:
                    print(f"    Found {len(results)} results on {mirror}")
                    break  # Found results, stop trying mirrors
                    
        except Exception as e:
            print(f"    {mirror} failed: {type(e).__name__}")
            continue
    
    return results


def get_download_links(detail_url: str) -> List[str]:
    """
    Get download links from Anna's Archive detail page.
    """
    download_links = []
    
    try:
        headers = {'User-Agent': UA}
        response = requests.get(detail_url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Anna's Archive has multiple download options
            # Look for "Fast downloads" section
            for link in soup.find_all('a', href=True):
                href = link['href']
                
                # Direct download links
                if any(x in href for x in ['download', 'get.php', 'main/', 'fast']):
                    if href.startswith('/'):
                        # Relative URL - need to construct full URL
                        base = detail_url.split('/md5/')[0]
                        href = base + href
                    
                    if href.startswith('http'):
                        download_links.append(href)
            
            # Also look for external links (LibGen, Z-Lib mirrors)
            for link in soup.select('a[href*="libgen"], a[href*="zlibrary"], a[href*="library.lol"]'):
                download_links.append(link['href'])
                
    except Exception:
        pass
    
    return download_links


def try_download_from_annas(download_url: str, output_file: Path) -> bool:
    """
    Try to download PDF from a given URL.
    """
    try:
        headers = {
            'User-Agent': UA,
            'Accept': 'application/pdf,*/*',
        }
        
        response = requests.get(download_url, headers=headers, timeout=30, allow_redirects=True)
        
        # Check if it's a PDF
        if response.content.startswith(b'%PDF'):
            # Validate size (>50KB to avoid stubs)
            if len(response.content) > 50 * 1024:
                with output_file.open('wb') as f:
                    f.write(response.content)
                return True
        
        # If HTML, might be a download page - parse for PDF link
        elif b'<html' in response.content[:100].lower():
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for PDF download link
            for link in soup.find_all('a', href=True):
                if 'pdf' in link['href'].lower() or 'download' in link['href'].lower():
                    pdf_url = link['href']
                    if not pdf_url.startswith('http'):
                        from urllib.parse import urljoin
                        pdf_url = urljoin(download_url, pdf_url)
                    
                    # Recursive call (only once to avoid loops)
                    pdf_resp = requests.get(pdf_url, headers=headers, timeout=30)
                    if pdf_resp.content.startswith(b'%PDF') and len(pdf_resp.content) > 50*1024:
                        with output_file.open('wb') as f:
                            f.write(pdf_resp.content)
                        return True
                    
    except Exception:
        pass
    
    return False


def try_fetch_from_annas_archive(doi: str, title: str, output_file: Path, isbn: str = None, authors: list = None, browser_callback=None) -> bool:
    """
    Main entry point for Anna's Archive.
    
    Tries multiple search strategies:
    1. ISBN search (best for books)
    2. DOI search (fastest for papers)
    3. Exact title search (for books/chapters)
    4. Fuzzy title search (if exact fails)
    
    Args:
        doi: DOI (for papers)
        title: Title to search for
        output_file: Where to save PDF
        isbn: ISBN (for books)
        authors: List of author names for validation
    """
    print("  🏴‍☠️ Searching Anna's Archive (100M+ items)...")
    
    # Strategy 0: ISBN search (BEST for books!)
    if isbn:
        print(f"    → Searching by ISBN: {isbn}...")
        results = search_annas_archive(isbn, 'isbn')
        
        if results:
            print(f"    Found {len(results)} result(s)")
            
            # Validate results against title if provided
            from difflib import SequenceMatcher
            
            for result in results[:5]:  # Try top 5
                result_title = result['title']
                
                # Smart validation with multiple checks
                is_valid = False
                validation_reason = ""
                
                if title:
                    # 1. Title similarity checks
                    full_similarity = SequenceMatcher(None, title.lower(), result_title.lower()).ratio()
                    substring_match = title.lower() in result_title.lower()
                    
                    # Check first N words (for "Title: Subtitle" cases)
                    title_words = title.lower().split()[:5]
                    result_words = result_title.lower().split()[:5]
                    word_similarity = SequenceMatcher(None, ' '.join(title_words), ' '.join(result_words)).ratio()
                    
                    best_similarity = max(full_similarity, word_similarity)
                    
                    # 2. Author validation (if we have authors)
                    author_match = False
                    if authors and len(authors) > 0:
                        # Check if any author name appears in result title or URL
                        result_text = (result_title + ' ' + result.get('url', '')).lower()
                        for author in authors:
                            # Check last name (most reliable)
                            author_parts = author.lower().split()
                            if len(author_parts) > 0:
                                last_name = author_parts[-1]
                                if len(last_name) > 3 and last_name in result_text:
                                    author_match = True
                                    break
                    
                    # 3. ISBN validation (check if ISBN appears in URL)
                    isbn_in_url = False
                    if isbn:
                        # Remove hyphens from ISBN for matching
                        clean_isbn = isbn.replace('-', '')
                        if clean_isbn in result.get('url', ''):
                            isbn_in_url = True
                    
                    # Decision logic: Accept if ANY of these is true
                    if best_similarity >= 0.7:
                        is_valid = True
                        validation_reason = f"similarity: {best_similarity:.2f}"
                    elif substring_match and best_similarity >= 0.5:
                        is_valid = True
                        validation_reason = f"substring match + {best_similarity:.2f}"
                    elif author_match and best_similarity >= 0.4:
                        is_valid = True
                        validation_reason = f"author match + {best_similarity:.2f}"
                    elif isbn_in_url:
                        is_valid = True
                        validation_reason = "ISBN in URL"
                    
                    if is_valid:
                        print(f"    ✓ Trying: {result_title[:60]}... ({validation_reason})")
                    else:
                        print(f"    ✗ Skipping: {result_title[:60]}... (similarity: {best_similarity:.2f}, no author/ISBN match)")
                        continue
                else:
                    print(f"    Trying: {result_title[:60]}...")
                    is_valid = True
                
                download_links = get_download_links(result['url'])
                
                if not download_links:
                    print(f"      ✗ No download links found on detail page")
                    continue
                
                print(f"      Found {len(download_links)} download link(s)")
                
                # Try to download
                downloaded = False
                for dl_url in download_links[:5]:
                    if try_download_from_annas(dl_url, output_file):
                        print(f"    ✓ Downloaded from Anna's Archive (ISBN match)!")
                        return True
                
                # If download failed but we found the page, open in browser (like OA papers)
                if browser_callback and not downloaded:
                    print(f"    📖 Found on Anna's Archive, opening in browser...")
                    browser_callback(result['url'])
                    return True
    
    # Strategy 1: DOI search (with ISBN extraction for books)
    if doi:
        print(f"    → Searching by DOI: {doi}...")
        
        # For book chapters, extract ISBN from DOI
        # Format: 10.1007/978-3-030-47253-5_396-1 → ISBN: 978-3-030-47253-5
        if '978-' in doi or '979-' in doi:
            import re
            isbn_match = re.search(r'(97[89]-[\d-]+)', doi)
            if isbn_match:
                extracted_isbn = isbn_match.group(1).replace('-', '')
                print(f"    📖 Extracted ISBN from DOI: {extracted_isbn}")
                # Try ISBN search first (better for books)
                isbn_results = search_annas_archive(extracted_isbn, 'isbn')
                if isbn_results:
                    print(f"    Found {len(isbn_results)} book(s) by ISBN")
                    for result in isbn_results[:2]:
                        print(f"    Trying: {result['title'][:60]}...")
                        download_links = get_download_links(result['url'])
                        for dl_url in download_links[:5]:
                            if try_download_from_annas(dl_url, output_file):
                                print(f"    ✓ Downloaded from Anna's Archive (ISBN)!")
                                return True
        
        # Regular DOI search
        results = search_annas_archive(doi, 'doi')
        
        if results:
            print(f"    Found {len(results)} result(s)")
            
            for result in results[:3]:  # Try top 3
                print(f"    Trying: {result['title'][:60]}...")
                
                download_links = get_download_links(result['url'])
                
                for dl_url in download_links[:5]:  # Try up to 5 download links
                    if try_download_from_annas(dl_url, output_file):
                        print(f"    ✓ Downloaded from Anna's Archive!")
                        return True
    
    # Strategy 2: Title search (exact then fuzzy)
    if title:
        print(f"    → Searching by title...")
        
        # Try exact phrase first
        results = search_annas_archive(f'"{title}"', 'title')
        
        # If no results, try without quotes (fuzzy)
        if not results:
            print(f"    → Trying fuzzy title search...")
            results = search_annas_archive(title, 'title')
        
        if results:
            print(f"    Found {len(results)} result(s)")
            
            # Check title similarity
            from difflib import SequenceMatcher
            
            for result in results[:10]:  # Try more results for title search
                result_title = result['title']
                similarity = SequenceMatcher(None, title.lower(), result_title.lower()).ratio()
                
                # Robust validation
                is_valid = False
                validation_reason = ""
                
                # Check authors if available
                author_match = False
                if authors:
                    result_text = (result_title + ' ' + result.get('url', '')).lower()
                    for author in authors:
                        author_parts = author.lower().split()
                        if len(author_parts) > 0:
                            last_name = author_parts[-1]
                            if len(last_name) > 3 and last_name in result_text:
                                author_match = True
                                break
                
                if similarity >= 0.8:
                    is_valid = True
                    validation_reason = f"high similarity: {similarity:.2f}"
                elif author_match and similarity >= 0.5:
                    is_valid = True
                    validation_reason = f"author match + similarity: {similarity:.2f}"
                
                if is_valid:
                    print(f"    Trying: {result_title[:60]}... ({validation_reason})")
                    
                    download_links = get_download_links(result['url'])
                    
                    if not download_links:
                        print(f"      ✗ No download links found on detail page")
                        continue
                    
                    print(f"      Found {len(download_links)} download link(s)")
                    
                    # Try to download
                    downloaded = False
                    for dl_url in download_links[:3]:
                        if try_download_from_annas(dl_url, output_file):
                            print(f"    ✓ Downloaded from Anna's Archive!")
                            return True
                    
                    # If download failed but we found a good match, open in browser (like OA papers)
                    if browser_callback and not downloaded:
                        print(f"    📖 Found on Anna's Archive (title match), opening in browser...")
                        browser_callback(result['url'])
                        return True
                else:
                    print(f"    Skipping: {result_title[:60]}... (similarity: {similarity:.2f} too low/no author match)")
    
    print("    ✗ Not found on Anna's Archive")
    return False


def try_fetch_book_chapter(title: str, book_title: str, output_file: Path) -> bool:
    """
    Specialized search for book chapters.
    
    Many "papers" are actually book chapters (conference proceedings, encyclopedias, etc.)
    Anna's Archive is EXCELLENT for these.
    """
    print("  📚 Searching for book chapter...")
    
    # Search for the book (not the chapter)
    if book_title:
        print(f"    → Searching book: {book_title[:60]}...")
        results = search_annas_archive(book_title, 'title')
        
        if results:
            # Download the book (which contains the chapter)
            for result in results[:2]:
                download_links = get_download_links(result['url'])
                
                for dl_url in download_links[:2]:
                    if try_download_from_annas(dl_url, output_file):
                        print(f"    ✓ Downloaded book containing chapter!")
                        return True
    
    return False
