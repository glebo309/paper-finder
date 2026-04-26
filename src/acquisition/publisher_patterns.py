#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Publisher-specific URL pattern guessing for PDF discovery.

Many publishers have predictable URL patterns for PDFs that aren't
always linked in the HTML. This module tries common patterns.
"""

import re
from pathlib import Path
from typing import Optional, List, Tuple
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _validate_pdf_response(response: requests.Response) -> bool:
    """Check if response is actually a PDF"""
    content_type = response.headers.get('content-type', '').lower()
    if 'pdf' in content_type:
        return True
    
    # Check first few bytes for PDF magic number
    if len(response.content) >= 4 and response.content[:4] == b'%PDF':
        return True
    
    return False


# ============================================================================
# SPRINGER / NATURE
# ============================================================================

def try_springer_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try Springer/Nature URL patterns.
    
    Common patterns:
    - /article/{doi}/pdf
    - /content/pdf/{doi}.pdf
    - /track/pdf/{doi}
    """
    candidates = []
    
    # Extract base URL
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    
    # Pattern 1: /article/{doi}/pdf
    candidates.append(f"{base}/article/{doi}/pdf")
    
    # Pattern 2: Direct PDF link
    if '/article/' in article_url:
        pdf_url = article_url.replace('/article/', '/content/pdf/') + '.pdf'
        candidates.append(pdf_url)
    
    # Pattern 3: Track PDF
    candidates.append(f"{base}/track/pdf/{doi}")
    
    # Pattern 4: epdf
    candidates.append(f"{base}/epdf/{doi}")
    
    return candidates


# ============================================================================
# ELSEVIER / SCIENCEDIRECT
# ============================================================================

def try_elsevier_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try Elsevier/ScienceDirect URL patterns.
    
    Common patterns:
    - /science/article/pii/{PII}/pdfft
    - /science/article/pii/{PII}/pdf
    """
    candidates = []
    
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    
    # Extract PII if present
    pii_match = re.search(r'/pii/([A-Z0-9]+)', article_url)
    if pii_match:
        pii = pii_match.group(1)
        candidates.append(f"{base}/science/article/pii/{pii}/pdfft")
        candidates.append(f"{base}/science/article/pii/{pii}/pdf")
    
    return candidates


# ============================================================================
# WILEY
# ============================================================================

def try_wiley_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try Wiley URL patterns.
    
    Common patterns:
    - /doi/pdf/{doi}
    - /doi/pdfdirect/{doi}
    - /doi/epdf/{doi}
    """
    candidates = []
    
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    
    candidates.append(f"{base}/doi/pdf/{doi}")
    candidates.append(f"{base}/doi/pdfdirect/{doi}")
    candidates.append(f"{base}/doi/epdf/{doi}")
    candidates.append(f"{base}/doi/full-xml/{doi}")
    
    return candidates


# ============================================================================
# IEEE
# ============================================================================

def try_ieee_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try IEEE URL patterns.
    
    Common patterns:
    - /stamp/stamp.jsp?tp=&arnumber={id}
    - /iel7/{path}/document/{id}/pdf
    """
    candidates = []
    
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    
    # Extract article number
    arnumber_match = re.search(r'arnumber=(\d+)', article_url)
    if arnumber_match:
        arnumber = arnumber_match.group(1)
        candidates.append(f"{base}/stamp/stamp.jsp?tp=&arnumber={arnumber}")
    
    # Extract document ID
    doc_match = re.search(r'/document/(\d+)', article_url)
    if doc_match:
        doc_id = doc_match.group(1)
        candidates.append(f"{base}/document/{doc_id}/pdf")
    
    return candidates


# ============================================================================
# ACS (American Chemical Society)
# ============================================================================

def try_acs_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try ACS URL patterns.
    
    Common patterns:
    - /doi/pdf/{doi}
    - /doi/pdfplus/{doi}
    """
    candidates = []
    
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    
    candidates.append(f"{base}/doi/pdf/{doi}")
    candidates.append(f"{base}/doi/pdfplus/{doi}")
    
    return candidates


# ============================================================================
# TAYLOR & FRANCIS
# ============================================================================

def try_taylorfrancis_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try Taylor & Francis URL patterns.
    
    Common patterns:
    - /doi/pdf/{doi}
    - /doi/epdf/{doi}
    """
    candidates = []
    
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    
    candidates.append(f"{base}/doi/pdf/{doi}")
    candidates.append(f"{base}/doi/epdf/{doi}")
    
    return candidates


# ============================================================================
# SAGE
# ============================================================================

def try_sage_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try SAGE URL patterns.
    
    Common patterns:
    - /doi/pdf/{doi}
    - /doi/reader/{doi}
    """
    candidates = []
    
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    
    candidates.append(f"{base}/doi/pdf/{doi}")
    candidates.append(f"{base}/doi/reader/{doi}")
    
    return candidates


# ============================================================================
# OXFORD ACADEMIC
# ============================================================================

def try_oxford_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try Oxford Academic URL patterns.
    
    Common patterns:
    - /article/{doi}/pdf
    - /{journal}/article-pdf/{volume}/{issue}/{pages}/{doi}.pdf
    """
    candidates = []
    
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    
    candidates.append(f"{base}/article/{doi}/pdf")
    
    # Try to extract article path
    if '/article/' in article_url:
        article_path = article_url.split('/article/')[1]
        candidates.append(f"{base}/article-pdf/{article_path}")
    
    return candidates


# ============================================================================
# CAMBRIDGE
# ============================================================================

def try_cambridge_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try Cambridge URL patterns.
    
    Common patterns:
    - /core/services/aop-cambridge-core/content/view/{id}
    """
    candidates = []
    
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    
    # Extract article ID if present
    if '/article/' in article_url:
        candidates.append(article_url.replace('/article/', '/article/pdf/'))
    
    return candidates


# ============================================================================
# SUPPLEMENTAL MATERIAL PATTERNS
# ============================================================================

def try_supplemental_patterns(doi: str, article_url: str) -> List[str]:
    """
    Try common supplemental material URL patterns.
    
    Many publishers host supplemental PDFs in predictable locations.
    """
    candidates = []
    
    parsed = urlparse(article_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path
    
    # Common supplemental directories
    suppl_dirs = [
        '/suppl/',
        '/si/',
        '/supplementary/',
        '/material/',
        '/resources/',
        '/supporting-information/',
        '/data/',
    ]
    
    for suppl_dir in suppl_dirs:
        # Try appending to base path
        candidates.append(f"{base}{path}{suppl_dir}main.pdf")
        candidates.append(f"{base}{path}{suppl_dir}supplement.pdf")
        candidates.append(f"{base}{path}{suppl_dir}SI.pdf")
        
    return candidates


# ============================================================================
# MASTER FUNCTION
# ============================================================================

def guess_publisher_pdf_urls(doi: str, article_url: str, publisher: str = None) -> List[str]:
    """
    Guess possible PDF URLs based on publisher and article URL.
    
    Args:
        doi: Paper DOI
        article_url: Article landing page URL
        publisher: Publisher name (optional, will be guessed from URL)
    
    Returns:
        List of candidate PDF URLs to try
    """
    if not article_url:
        return []
    
    candidates = []
    url_lower = article_url.lower()
    
    # Detect publisher from URL if not provided
    if not publisher:
        if 'springer' in url_lower or 'nature.com' in url_lower:
            publisher = 'springer'
        elif 'sciencedirect' in url_lower or 'elsevier' in url_lower:
            publisher = 'elsevier'
        elif 'wiley' in url_lower:
            publisher = 'wiley'
        elif 'ieee' in url_lower:
            publisher = 'ieee'
        elif 'acs.org' in url_lower:
            publisher = 'acs'
        elif 'tandfonline' in url_lower:
            publisher = 'taylorfrancis'
        elif 'sagepub' in url_lower:
            publisher = 'sage'
        elif 'oxford' in url_lower:
            publisher = 'oxford'
        elif 'cambridge' in url_lower:
            publisher = 'cambridge'
    
    # Try publisher-specific patterns
    if publisher == 'springer':
        candidates.extend(try_springer_patterns(doi, article_url))
    elif publisher == 'elsevier':
        candidates.extend(try_elsevier_patterns(doi, article_url))
    elif publisher == 'wiley':
        candidates.extend(try_wiley_patterns(doi, article_url))
    elif publisher == 'ieee':
        candidates.extend(try_ieee_patterns(doi, article_url))
    elif publisher == 'acs':
        candidates.extend(try_acs_patterns(doi, article_url))
    elif publisher == 'taylorfrancis':
        candidates.extend(try_taylorfrancis_patterns(doi, article_url))
    elif publisher == 'sage':
        candidates.extend(try_sage_patterns(doi, article_url))
    elif publisher == 'oxford':
        candidates.extend(try_oxford_patterns(doi, article_url))
    elif publisher == 'cambridge':
        candidates.extend(try_cambridge_patterns(doi, article_url))
    
    # Always try supplemental patterns
    candidates.extend(try_supplemental_patterns(doi, article_url))
    
    # Remove duplicates while preserving order
    seen = set()
    unique_candidates = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique_candidates.append(url)
    
    return unique_candidates


def try_fetch_from_publisher_patterns(
    doi: str,
    article_url: str,
    outpath: Path,
    publisher: str = None
) -> Optional[str]:
    """
    Try to fetch PDF using publisher URL patterns.
    
    Returns the pattern type if successful, None otherwise.
    """
    if not article_url:
        return None
    
    candidates = guess_publisher_pdf_urls(doi, article_url, publisher)
    
    if not candidates:
        return None
    
    print(f"  Found {len(candidates)} publisher pattern candidates")
    
    session = requests.Session()
    session.headers.update({'User-Agent': UA})
    
    for url in candidates:
        try:
            print(f"  Trying pattern: {url[:80]}...")
            
            response = session.get(url, timeout=20, allow_redirects=True)
            
            # Check if it's actually a PDF
            if not _validate_pdf_response(response):
                print(f"    ✗ Not a valid PDF")
                continue
            
            # Check file size
            if len(response.content) < 50 * 1024:  # Less than 50KB
                print(f"    ✗ File too small (< 50KB)")
                continue
            
            # Save to file
            with outpath.open('wb') as f:
                f.write(response.content)
            
            print(f"  ✓ Successfully downloaded via pattern guessing")
            return "publisher_pattern"
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                print(f"    ✗ Access forbidden (paywall)")
            elif e.response.status_code == 404:
                print(f"    ✗ Not found")
            else:
                print(f"    ✗ HTTP error: {e.response.status_code}")
            continue
        except Exception as e:
            print(f"    ✗ Failed: {type(e).__name__}")
            continue
    
    return None


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    # Test pattern generation
    test_cases = [
        {
            "doi": "10.1038/nature12373",
            "url": "https://www.nature.com/articles/nature12373",
            "publisher": "springer"
        },
        {
            "doi": "10.1016/j.cell.2020.01.001",
            "url": "https://www.sciencedirect.com/science/article/pii/S0092867420300010",
            "publisher": "elsevier"
        },
        {
            "doi": "10.1002/anie.202000000",
            "url": "https://onlinelibrary.wiley.com/doi/10.1002/anie.202000000",
            "publisher": "wiley"
        }
    ]
    
    print("=" * 80)
    print("Testing Publisher Pattern Guessing")
    print("=" * 80)
    print()
    
    for test in test_cases:
        print(f"DOI: {test['doi']}")
        print(f"URL: {test['url']}")
        print(f"Publisher: {test['publisher']}")
        
        patterns = guess_publisher_pdf_urls(test['doi'], test['url'], test['publisher'])
        
        print(f"Generated {len(patterns)} patterns:")
        for i, pattern in enumerate(patterns[:5], 1):  # Show first 5
            print(f"  {i}. {pattern}")
        
        print()
