#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ENHANCED Deep web crawler for exhaustive PDF search.

Major improvements:
1. Multiple search engines (Google, DuckDuckGo, Bing Academic)
2. ORCID integration for author identification
3. ResearchGate & Academia.edu scraping
4. Affiliation domain extraction (.edu, .ac.uk, etc.)
5. More aggressive search (5 authors, 5 homepages, 6 queries)
6. DOI-based search on author pages
7. Enhanced repository patterns (30+ indicators)
8. Semantic title matching (fuzzy matching, 50% threshold)
9. Retry logic with exponential backoff
10. Direct preprint server search (arXiv, bioRxiv, ChemRxiv)
"""

import re
import time
import random
from pathlib import Path
from typing import Optional, List, Dict, Set, Tuple
from urllib.parse import quote, urljoin, urlparse, unquote
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Academic profile platforms
ACADEMIC_PLATFORMS = {
    'researchgate.net': 'ResearchGate',
    'academia.edu': 'Academia.edu',
    'orcid.org': 'ORCID',
    'scholar.google': 'Google Scholar',
    'linkedin.com/in': 'LinkedIn',
    'arxiv.org': 'arXiv',
    'biorxiv.org': 'bioRxiv',
    'chemrxiv.org': 'ChemRxiv',
}

# Preprint servers
PREPRINT_SERVERS = [
    'arxiv.org',
    'biorxiv.org',
    'chemrxiv.org',
    'medrxiv.org',
    'ssrn.com',
    'preprints.org',
    'osf.io/preprints',
]


def extract_author_info(metadata: Dict) -> List[Dict]:
    """Extract author names and affiliations from metadata"""
    authors = []
    
    # Try to get raw Crossref data first (preferred, has affiliation info)
    raw_data = metadata.get('raw', {})
    author_list = raw_data.get('author', [])
    
    # Fall back to simple author list if no raw data
    if not author_list:
        author_list = metadata.get('author', [])
        # If authors is a list of strings, convert to dicts
        if author_list and isinstance(author_list[0], str):
            for author_name in author_list:
                authors.append({
                    'name': author_name,
                    'affiliation': ''
                })
            return authors
    
    # Process raw Crossref author data (has affiliation info)
    for author in author_list:
        if isinstance(author, dict):
            name = f"{author.get('given', '')} {author.get('family', '')}".strip()
            affiliation = author.get('affiliation', [])
            
            if affiliation and len(affiliation) > 0:
                aff_name = affiliation[0].get('name', '')
            else:
                aff_name = ''
            
            authors.append({
                'name': name,
                'affiliation': aff_name
            })
    
    return authors


def extract_domain_from_affiliation(affiliation: str) -> Optional[str]:
    """
    Extract institutional domain from affiliation string.
    
    Examples:
        "University of Toronto" -> "utoronto.ca"
        "MIT" -> "mit.edu"
        "Stanford University" -> "stanford.edu"
    """
    if not affiliation:
        return None
    
    affiliation_lower = affiliation.lower()
    
    # Common university domain patterns
    domain_map = {
        'mit': 'mit.edu',
        'stanford': 'stanford.edu',
        'harvard': 'harvard.edu',
        'yale': 'yale.edu',
        'princeton': 'princeton.edu',
        'caltech': 'caltech.edu',
        'berkeley': 'berkeley.edu',
        'ucla': 'ucla.edu',
        'oxford': 'ox.ac.uk',
        'cambridge': 'cam.ac.uk',
        'toronto': 'utoronto.ca',
        'eth zurich': 'ethz.ch',
        'imperial college': 'imperial.ac.uk',
    }
    
    for key, domain in domain_map.items():
        if key in affiliation_lower:
            return domain
    
    # Try to extract domain from affiliation if it contains one
    domain_pattern = r'(?:[\w-]+\.)+(?:edu|ac\.uk|ac\.cn|edu\.au|edu\.cn)'
    match = re.search(domain_pattern, affiliation_lower)
    if match:
        return match.group(0)
    
    return None


def similarity_score(text1: str, text2: str) -> float:
    """Calculate similarity between two strings (0-1)"""
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def title_matches(link_text: str, paper_title: str, threshold: float = 0.5) -> bool:
    """Check if link text matches paper title using fuzzy matching"""
    if not link_text or not paper_title:
        return False
    
    # Try exact word overlap first
    title_words = set(paper_title.lower().split())
    title_words = {w for w in title_words if len(w) > 3}
    link_words = set(link_text.lower().split())
    
    if title_words:
        overlap = len(title_words & link_words) / len(title_words)
        if overlap >= 0.4:  # 40% word overlap
            return True
    
    # Try fuzzy matching
    score = similarity_score(link_text, paper_title)
    return score >= threshold


def search_with_retry(url: str, max_retries: int = 3) -> Optional[requests.Response]:
    """Make HTTP request with retry logic and exponential backoff"""
    headers = {'User-Agent': UA}
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:  # Rate limited
                wait_time = (2 ** attempt) * random.uniform(1, 2)
                time.sleep(wait_time)
                continue
            else:
                return None
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(random.uniform(1, 2))
                continue
            return None
    
    return None


def search_duckduckgo(query: str, num_results: int = 10) -> List[str]:
    """Search DuckDuckGo (no rate limiting, good for academic content)"""
    urls = []
    seen = set()
    
    try:
        search_url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        response = search_with_retry(search_url)
        
        if not response:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # DuckDuckGo HTML format
        for result in soup.find_all('a', class_='result__url'):
            href = result.get('href', '')
            if href and href not in seen and href.startswith('http'):
                seen.add(href)
                urls.append(href)
                if len(urls) >= num_results:
                    break
        
        # Alternative: extract from snippet links
        if not urls:
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if '/uddg=' in href:  # DuckDuckGo redirect
                    try:
                        actual_url = unquote(href.split('/uddg=')[1].split('&')[0])
                        if actual_url not in seen and actual_url.startswith('http'):
                            seen.add(actual_url)
                            urls.append(actual_url)
                            if len(urls) >= num_results:
                                break
                    except:
                        continue
    except Exception as e:
        pass
    
    return urls[:num_results]


def search_bing_academic(query: str, num_results: int = 10) -> List[str]:
    """Search Bing Academic (good for scholarly content)"""
    urls = []
    seen = set()
    
    try:
        search_url = f"https://www.bing.com/search?q={quote(query)}"
        response = search_with_retry(search_url)
        
        if not response:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for result in soup.find_all('li', class_='b_algo'):
            link = result.find('a', href=True)
            if link:
                href = link.get('href', '')
                if href and href not in seen and href.startswith('http'):
                    seen.add(href)
                    urls.append(href)
                    if len(urls) >= num_results:
                        break
    except Exception as e:
        pass
    
    return urls[:num_results]


def search_google(query: str, num_results: int = 10) -> List[str]:
    """Search Google (classic, but rate-limited)"""
    urls = []
    seen = set()
    
    try:
        search_url = f"https://www.google.com/search?q={quote(query)}&num={num_results}"
        response = search_with_retry(search_url)
        
        if not response:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            
            # Extract actual URL from Google redirect
            actual_url = None
            if '/url?q=' in href:
                actual_url = href.split('/url?q=')[1].split('&')[0]
            elif href.startswith('http'):
                actual_url = href
            
            if actual_url and actual_url not in seen:
                seen.add(actual_url)
                urls.append(actual_url)
                if len(urls) >= num_results:
                    break
    except Exception as e:
        pass
    
    return urls[:num_results]


def multi_engine_search(query: str, num_results: int = 15) -> List[str]:
    """Search using multiple engines and combine results"""
    all_urls = []
    seen = set()
    
    # Try all engines
    engines = [
        ('DuckDuckGo', lambda: search_duckduckgo(query, num_results)),
        ('Google', lambda: search_google(query, num_results)),
        ('Bing', lambda: search_bing_academic(query, num_results)),
    ]
    
    for engine_name, search_func in engines:
        try:
            urls = search_func()
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    all_urls.append(url)
        except Exception as e:
            continue
        
        # Small delay between engines
        time.sleep(random.uniform(1, 2))
    
    return all_urls[:num_results * 2]  # Return up to 2x the requested number


def find_orcid(author_name: str) -> Optional[str]:
    """Find author's ORCID ID"""
    try:
        query = f'"{author_name}"'
        search_url = f"https://pub.orcid.org/v3.0/search/?q={quote(query)}"
        
        headers = {
            'User-Agent': UA,
            'Accept': 'application/json'
        }
        
        response = requests.get(search_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            results = data.get('result', [])
            if results:
                # Get first result's ORCID
                orcid_id = results[0].get('orcid-identifier', {}).get('path')
                return orcid_id
    except Exception as e:
        pass
    
    return None


def search_academic_profiles(author_name: str, affiliation: str = None) -> List[Tuple[str, str]]:
    """
    Search for author on academic profile platforms.
    
    Returns list of (platform_name, url) tuples.
    """
    profiles = []
    
    # Build queries
    base_query = f'"{author_name}"'
    if affiliation:
        base_query += f' {affiliation}'
    
    # Try each platform
    platform_queries = [
        ('ResearchGate', f'{base_query} site:researchgate.net'),
        ('Academia.edu', f'{base_query} site:academia.edu'),
        ('Google Scholar', f'{base_query} site:scholar.google.com'),
    ]
    
    for platform, query in platform_queries:
        try:
            urls = multi_engine_search(query, num_results=3)
            for url in urls:
                if any(domain in url.lower() for domain in ACADEMIC_PLATFORMS.keys()):
                    profiles.append((platform, url))
                    break  # Only need one URL per platform
        except Exception as e:
            continue
    
    # Try ORCID
    try:
        orcid_id = find_orcid(author_name)
        if orcid_id:
            profiles.append(('ORCID', f'https://orcid.org/{orcid_id}'))
    except:
        pass
    
    return profiles


def find_author_homepage(author_name: str, affiliation: str = None) -> List[str]:
    """
    Find author's homepage using multiple search strategies.
    
    ENHANCED: Uses 3 search engines, 6 queries, lower thresholds
    """
    if not author_name:
        return []
    
    homepages = []
    seen = set()
    
    # Extract domain from affiliation if possible
    affiliation_domain = extract_domain_from_affiliation(affiliation) if affiliation else None
    
    # Try multiple query patterns (INCREASED from 4 to 6)
    queries = [
        f'"{author_name}" {affiliation} homepage' if affiliation else f'"{author_name}" homepage',
        f'"{author_name}" {affiliation} publications' if affiliation else f'"{author_name}" publications',
        f'"{author_name}" {affiliation} CV' if affiliation else f'"{author_name}" CV',
        f'"{author_name}" professor {affiliation}' if affiliation else f'"{author_name}" professor',
        f'"{author_name}" site:.edu' if not affiliation else f'"{author_name}" site:.edu {affiliation}',
        f'"{author_name}" faculty' if not affiliation_domain else f'"{author_name}" site:{affiliation_domain}',
    ]
    
    # Extended list of academic domains
    academic_domains = [
        '.edu', '.ac.uk', '.ac.cn', '.edu.cn', '.edu.au', '.ac.jp',
        '.edu.br', '.ac.in', '.ac.za', '.edu.sg', '.ac.kr', '.edu.tw',
        '.edu.hk', '.ac.il', '.edu.mx', '.ac.at', '.edu.ar', '.ac.nz',
        '.uni-', '.univ-', '.ac.', '.edu.',  # Generic patterns
        '.fr', '.de', '.nl', '.se', '.no', '.fi', '.dk', '.es', '.pt', '.it',  # European
        '.edu.co', '.edu.my', '.ac.th', '.edu.eg', '.ac.ir',  # More countries
    ]
    
    # Indicators of personal/faculty pages
    personal_indicators = [
        '/~', '/people/', '/faculty/', '/staff/', '/members/', '/team/',
        '/professor/', '/prof/', '/researcher/', '/personal/', '/home/',
        '/research/', '/lab/', '/group/', '/user/', '/profile/',
        'homepage', 'faculty', 'staff', 'profile', 'people'
    ]
    
    # Try first 4 queries (INCREASED from 2)
    for query in queries[:4]:
        try:
            # Use multi-engine search
            urls = multi_engine_search(query, num_results=15)
            
            for actual_url in urls:
                if actual_url in seen:
                    continue
                
                seen.add(actual_url)
                url_lower = actual_url.lower()
                
                # Score the URL
                score = 0
                
                # Check for academic domain
                for domain in academic_domains:
                    if domain in url_lower:
                        score += 10
                        break
                
                # Bonus for affiliation domain
                if affiliation_domain and affiliation_domain in url_lower:
                    score += 15
                
                # Check for personal page indicators
                for indicator in personal_indicators:
                    if indicator in url_lower:
                        score += 5
                
                # Author name in URL is good sign
                name_parts = author_name.lower().split()
                for part in name_parts:
                    if len(part) > 3 and part in url_lower:
                        score += 3
                
                # LOWERED threshold from 5 to 3 for more results
                if score > 3:
                    homepages.append((score, actual_url))
        
        except Exception as e:
            continue
        
        # Small delay between queries
        time.sleep(random.uniform(1, 1.5))
    
    # Sort by score and return URLs (INCREASED from 5 to 8)
    homepages.sort(reverse=True)
    return [url for score, url in homepages[:8]]


def crawl_author_page(page_url: str, paper_title: str, doi: str = None) -> List[str]:
    """
    Crawl author's homepage for PDF links.
    
    ENHANCED: DOI search, fuzzy title matching, more patterns
    """
    if not page_url:
        return []
    
    pdf_urls = []
    
    try:
        response = search_with_retry(page_url)
        if not response:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all PDF links
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().strip()
            
            # Check if it's a PDF
            if href.lower().endswith('.pdf') or '/pdf' in href.lower():
                # Make absolute URL
                pdf_url = urljoin(page_url, href)
                
                # Check if link text matches paper title (FUZZY MATCHING)
                if title_matches(text, paper_title, threshold=0.4):
                    pdf_urls.insert(0, pdf_url)  # High priority
                elif doi and doi.lower() in href.lower():
                    pdf_urls.insert(0, pdf_url)  # DOI in URL = high priority
                else:
                    pdf_urls.append(pdf_url)  # Lower priority
        
        # Also check for "publications" or "papers" pages
        for link in soup.find_all('a', href=True):
            text = link.get_text().strip().lower()
            href = link['href']
            
            if any(word in text for word in ['publication', 'paper', 'research', 'cv', 'preprint']):
                pub_url = urljoin(page_url, href)
                if pub_url != page_url and pub_url not in seen_pages:  # Avoid infinite loop
                    seen_pages.add(pub_url)
                    sub_pdfs = _crawl_publications_page(pub_url, paper_title, doi)
                    pdf_urls.extend(sub_pdfs[:8])  # INCREASED from 5 to 8
        
    except Exception as e:
        pass
    
    return pdf_urls[:15]  # INCREASED from 10 to 15


# Track visited pages to avoid loops
seen_pages = set()


def _crawl_publications_page(page_url: str, paper_title: str, doi: str = None) -> List[str]:
    """Crawl a publications subpage"""
    pdf_urls = []
    
    try:
        response = search_with_retry(page_url)
        if not response:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().strip()
            
            if href.lower().endswith('.pdf') or '/pdf' in href.lower():
                pdf_url = urljoin(page_url, href)
                
                # FUZZY MATCHING
                if title_matches(text, paper_title, threshold=0.4):
                    pdf_urls.insert(0, pdf_url)
                elif doi and doi.lower() in href.lower():
                    pdf_urls.insert(0, pdf_url)
                else:
                    pdf_urls.append(pdf_url)
        
    except Exception as e:
        pass
    
    return pdf_urls[:10]


def search_preprint_servers(title: str, doi: str = None) -> List[str]:
    """Search preprint servers directly"""
    pdf_urls = []
    
    # Build query
    query = f'"{title}"'
    if doi:
        query += f' OR {doi}'
    
    for server in PREPRINT_SERVERS:
        try:
            search_query = f'{query} site:{server} filetype:pdf'
            urls = multi_engine_search(search_query, num_results=5)
            
            for url in urls:
                if server in url.lower() and url not in pdf_urls:
                    pdf_urls.append(url)
        except Exception as e:
            continue
    
    return pdf_urls[:10]


def search_institutional_repositories(title: str, affiliation: str = None, doi: str = None) -> List[str]:
    """
    Advanced institutional repository search using multiple strategies.
    
    ENHANCED: 30+ repository indicators, DOI search, more queries
    """
    pdf_urls = []
    seen_urls = set()
    
    # Repository indicators (EXPANDED from ~10 to 30+)
    repo_indicators = [
        'repository', 'dspace', 'eprints', 'scholarworks',
        'digitalcommons', 'pure', 'ora', 'research-repository',
        'digital.library', 'digitallibrary', 'ir.', 'thesis',
        'dissertation', 'archive', 'depot', 'openaccess',
        'handle.net', 'hdl.handle', 'figshare', 'zenodo',
        'researchgate', 'academia.edu', 'osf.io',
        'institutional-repository', 'open-repository',
        'publications', 'research-outputs', 'research-portal',
        'biblio', 'bibliotheque', 'biblioteca',
        'docs.', 'publications.', 'research.',
    ]
    
    # Try multiple search strategies (INCREASED queries)
    queries = [
        f'"{title}" filetype:pdf repository',
        f'"{title}" filetype:pdf site:edu',
        f'"{title}" filetype:pdf site:ac.uk',
        f'"{title}" pdf institutional repository',
        f'"{title}" "open access" pdf',
        f'"{title}" dspace OR eprints OR "digital commons"',
        f'"{title}" handle.net OR figshare OR zenodo',
    ]
    
    # Add DOI-based searches
    if doi:
        queries.extend([
            f'{doi} filetype:pdf',
            f'{doi} repository',
            f'{doi} "open access"',
        ])
    
    if affiliation:
        # Extract domain from affiliation
        affiliation_domain = extract_domain_from_affiliation(affiliation)
        
        # Add affiliation-specific searches
        queries.extend([
            f'"{title}" site:{affiliation_domain} pdf' if affiliation_domain else f'"{title}" "{affiliation}" pdf',
            f'"{title}" "{affiliation}" repository',
        ])
    
    # Try first 6 queries (INCREASED from 3)
    for query in queries[:6]:
        try:
            # Use multi-engine search
            urls = multi_engine_search(query, num_results=20)
            
            for actual_url in urls:
                if actual_url in seen_urls:
                    continue
                
                seen_urls.add(actual_url)
                url_lower = actual_url.lower()
                
                # Score the URL
                score = 0
                
                # Check for repository indicators
                for indicator in repo_indicators:
                    if indicator in url_lower:
                        score += 10
                        break
                
                # PDF indicators
                if '.pdf' in url_lower:
                    score += 20  # INCREASED from 15
                elif '/pdf' in url_lower or 'download' in url_lower or 'fulltext' in url_lower:
                    score += 12  # INCREASED from 10
                
                # DOI in URL
                if doi and doi.lower() in url_lower:
                    score += 15
                
                # Academic domain
                if any(domain in url_lower for domain in ['.edu', '.ac.', '.uni-', '.univ-']):
                    score += 5
                
                # Common repository paths
                if any(path in url_lower for path in ['/handle/', '/bitstream/', '/download/', '/article/', '/fulltext/']):
                    score += 8
                
                # Preprint servers
                if any(server in url_lower for server in PREPRINT_SERVERS):
                    score += 12
                
                # LOWERED threshold from 10 to 8
                if score >= 8:
                    pdf_urls.append((score, actual_url))
            
        except Exception as e:
            continue
        
        # Small delay
        time.sleep(random.uniform(1, 1.5))
    
    # Sort by score and return top URLs (INCREASED from 15 to 25)
    pdf_urls.sort(reverse=True)
    return [url for score, url in pdf_urls[:25]]


def try_fetch_deep_crawl(
    title: str,
    doi: str,
    outpath: Path,
    metadata: Dict = None
) -> Optional[str]:
    """
    Enhanced deep crawl using multiple strategies for author pages and repositories.
    
    MAJOR ENHANCEMENTS:
    - Multiple search engines (Google, DuckDuckGo, Bing)
    - ORCID integration
    - Academic profile scraping (ResearchGate, Academia.edu)
    - Preprint server search
    - 5 authors (up from 3)
    - 8 homepages per author (up from 2)
    - Fuzzy title matching
    - DOI-based search
    - More repository patterns
    - Retry logic
    """
    if not title:
        return None
    
    print("  Deep crawling author pages and repositories...")
    
    session = requests.Session()
    session.headers.update({'User-Agent': UA})
    
    # Extract author info
    authors = []
    if metadata:
        authors = extract_author_info(metadata)
    
    # STRATEGY 1: Try preprint servers first (fast and reliable)
    print("    Searching preprint servers...")
    preprint_urls = search_preprint_servers(title, doi)
    
    if preprint_urls:
        print(f"    Found {len(preprint_urls)} preprint candidates")
        
        for pdf_url in preprint_urls[:5]:
            try:
                print(f"      Trying preprint: {pdf_url[:60]}...")
                response = session.get(pdf_url, timeout=30, allow_redirects=True)
                
                if response.content[:4] == b'%PDF' and len(response.content) > 50 * 1024:
                    with outpath.open('wb') as f:
                        f.write(response.content)
                    print(f"  ✓ Downloaded from preprint server")
                    return 'preprint_server'
            except Exception as e:
                continue
    
    # STRATEGY 2: Institutional repositories (expanded search)
    print("    Searching institutional repositories...")
    
    first_affiliation = authors[0]['affiliation'] if authors else None
    repo_urls = search_institutional_repositories(title, first_affiliation, doi)
    
    if repo_urls:
        print(f"    Found {len(repo_urls)} repository candidates")
        
        for repo_url in repo_urls[:15]:  # INCREASED from 10
            try:
                # Check if it's direct PDF link
                if repo_url.lower().endswith('.pdf'):
                    print(f"      Trying direct PDF: {repo_url[:60]}...")
                    response = session.get(repo_url, timeout=30, allow_redirects=True)
                    
                    if response.content[:4] == b'%PDF' and len(response.content) > 50 * 1024:
                        with outpath.open('wb') as f:
                            f.write(response.content)
                        print(f"  ✓ Downloaded from institutional repository (direct)")
                        return 'institutional_repo'
                    continue
                
                # Visit repository page to find PDF
                response = session.get(repo_url, timeout=15)
                
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for PDF links with better patterns
                pdf_patterns = [
                    ('a', {'href': re.compile(r'.*\.pdf$', re.I)}),
                    ('a', {'href': re.compile(r'.*/bitstream/.*', re.I)}),
                    ('a', {'href': re.compile(r'.*/download.*', re.I)}),
                    ('a', {'href': re.compile(r'.*/fulltext.*', re.I)}),
                    ('a', {'class': re.compile(r'.*download.*', re.I)}),
                    ('a', {'class': re.compile(r'.*pdf.*', re.I)}),
                    ('a', {'id': re.compile(r'.*pdf.*', re.I)}),
                    ('a', {'id': re.compile(r'.*download.*', re.I)}),
                ]
                
                for tag, attrs in pdf_patterns:
                    for link in soup.find_all(tag, attrs):
                        href = link.get('href', '')
                        if not href:
                            continue
                        
                        pdf_url = urljoin(repo_url, href)
                        
                        try:
                            # Try to download
                            pdf_response = session.get(pdf_url, timeout=30)
                            
                            if pdf_response.content[:4] == b'%PDF' and len(pdf_response.content) > 50 * 1024:
                                with outpath.open('wb') as f:
                                    f.write(pdf_response.content)
                                
                                print(f"  ✓ Downloaded from institutional repository")
                                return 'institutional_repo'
                        except Exception:
                            continue
                
            except Exception as e:
                continue
    
    # STRATEGY 3: Author homepages and academic profiles
    if not authors:
        print("    No author information available")
        return None
    
    print(f"    Found {len(authors)} authors")
    
    # Try first 5 authors (INCREASED from 3)
    for i, author in enumerate(authors[:5]):
        author_name = author['name']
        affiliation = author['affiliation']
        
        if not author_name:
            continue
        
        print(f"    Searching for {author_name}...")
        
        # Search academic profiles (NEW)
        profiles = search_academic_profiles(author_name, affiliation)
        if profiles:
            print(f"      Found {len(profiles)} academic profiles")
        
        # Find author homepages (enhanced with multiple engines)
        homepages = find_author_homepage(author_name, affiliation)
        
        # Combine profiles and homepages
        all_pages = [url for _, url in profiles] + homepages
        
        if not all_pages:
            print(f"      No homepage found")
            continue
        
        print(f"      Found {len(all_pages)} potential pages")
        
        # Try each page (INCREASED from 2 to 5)
        for page_url in all_pages[:5]:
            print(f"      Checking: {page_url[:60]}...")
            
            # Crawl author page (with DOI search)
            pdf_urls = crawl_author_page(page_url, title, doi)
            
            if not pdf_urls:
                continue
            
            print(f"      Found {len(pdf_urls)} PDF candidates")
            
            # Try each PDF
            for pdf_url in pdf_urls[:10]:  # Try more PDFs
                try:
                    print(f"      Trying: {pdf_url[:60]}...")
                    
                    response = session.get(pdf_url, timeout=30, allow_redirects=True)
                    
                    # Validate PDF
                    if response.content[:4] != b'%PDF':
                        print(f"        ✗ Not a valid PDF")
                        continue
                    
                    if len(response.content) < 50 * 1024:
                        print(f"        ✗ File too small")
                        continue
                    
                    # Save
                    with outpath.open('wb') as f:
                        f.write(response.content)
                    
                    print(f"  ✓ Downloaded from author page/profile")
                    return 'author_homepage'
                    
                except Exception as e:
                    print(f"        ✗ Failed: {type(e).__name__}")
                continue
        
        time.sleep(random.uniform(1, 2))
    
    return None


if __name__ == "__main__":
    # Test
    test_author = "Geoffrey Hinton"
    test_affiliation = "University of Toronto"
    
    print(f"Testing enhanced author homepage search for: {test_author}")
    homepages = find_author_homepage(test_author, test_affiliation)
    
    if homepages:
        print(f"Found {len(homepages)} homepages:")
        for hp in homepages:
            print(f"  - {hp}")
    else:
        print("Not found")
