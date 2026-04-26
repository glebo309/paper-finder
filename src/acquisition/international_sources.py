#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
International academic source scraping for PDF retrieval.

Supports:
- China: Baidu Scholar, CNKI mirrors
- Russia: CyberLeninka
- Iran: SID.ir
- South Korea: KISS
- Spain: Dialnet
- France: HAL
- Brazil: SciELO
"""

import re
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# User agent for requests
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _clean_title(title: str) -> str:
    """Clean title for search queries"""
    if not title:
        return ""
    # Remove special characters that might break searches
    title = re.sub(r'[^\w\s\-]', ' ', title)
    # Collapse whitespace
    title = re.sub(r'\s+', ' ', title)
    return title.strip()


def _is_pdf_url(url: str) -> bool:
    """Check if URL likely points to a PDF"""
    if not url:
        return False
    url_lower = url.lower()
    return (
        url_lower.endswith('.pdf') or
        '/pdf' in url_lower or
        'filetype=pdf' in url_lower or
        'download' in url_lower
    )


def _validate_pdf_response(response: requests.Response) -> bool:
    """Check if response is actually a PDF"""
    content_type = response.headers.get('content-type', '').lower()
    if 'pdf' in content_type:
        return True
    
    # Check first few bytes for PDF magic number
    if response.content[:4] == b'%PDF':
        return True
    
    return False


def _titles_match(title1: str, title2: str, threshold: float = 0.7) -> bool:
    """
    Check if two titles match with fuzzy matching.
    
    Args:
        title1: First title
        title2: Second title
        threshold: Similarity threshold (0-1)
    
    Returns:
        True if titles are similar enough
    """
    if not title1 or not title2:
        return False
    
    # Normalize titles
    t1 = re.sub(r'[^\w\s]', '', title1.lower()).strip()
    t2 = re.sub(r'[^\w\s]', '', title2.lower()).strip()
    
    # Exact match
    if t1 == t2:
        return True
    
    # Check if one is substring of other (for shortened titles)
    if len(t1) > 20 and len(t2) > 20:
        if t1 in t2 or t2 in t1:
            return True
    
    # Token-based Jaccard similarity
    tokens1 = set(t1.split())
    tokens2 = set(t2.split())
    
    if not tokens1 or not tokens2:
        return False
    
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)
    
    similarity = intersection / union if union > 0 else 0
    
    return similarity >= threshold


# ============================================================================
# CHINA - Baidu Scholar
# ============================================================================

def search_baidu_scholar(title: str, doi: str = "") -> List[str]:
    """
    Search Baidu Scholar (百度学术) for PDFs.
    
    Baidu Scholar indexes many Chinese university repositories that contain
    English papers with publicly accessible PDFs.
    
    Returns list of candidate PDF URLs.
    """
    if not title:
        return []
    
    pdf_urls = []
    
    try:
        # Baidu Scholar search URL
        base_url = "https://xueshu.baidu.com/s"
        
        # Try with title
        params = {
            'wd': _clean_title(title),
            'rsv_bp': '0',
            'tn': 'SE_baiduxueshu_c1gjeupa',
            'rsv_spt': '3',
            'ie': 'utf-8',
            'f': '8',
            'rsv_bp': '1',
        }
        
        headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        
        session = requests.Session()
        response = session.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for PDF links in results
        # Baidu Scholar often links to university repositories
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # Look for direct PDF links
            if _is_pdf_url(href):
                if href.startswith('http'):
                    pdf_urls.append(href)
                continue
            
            # Look for links to Chinese university domains
            if any(domain in href for domain in ['.edu.cn', '.ac.cn', 'cnki.net']):
                # These might lead to PDFs, add them as candidates
                if href.startswith('http'):
                    pdf_urls.append(href)
        
        # Also check for "下载" (download) buttons
        for element in soup.find_all(['a', 'div', 'span'], class_=re.compile(r'download|下载', re.I)):
            if element.get('href'):
                href = element['href']
                if href.startswith('http'):
                    pdf_urls.append(href)
        
    except Exception as e:
        print(f"Baidu Scholar search failed: {e}")
    
    return pdf_urls[:10]  # Return top 10 candidates


def search_cnki_mirror(title: str, doi: str = "") -> List[str]:
    """
    Search CNKI mirrors for PDFs.
    
    Note: This searches public/open access portions only.
    Many Chinese universities mirror CNKI content.
    """
    if not title:
        return []
    
    pdf_urls = []
    
    # Common CNKI mirror patterns
    mirror_domains = [
        'cnki.net',
        'cnki.com.cn',
    ]
    
    try:
        # Use Google to find CNKI links (more reliable than direct CNKI search)
        query = f'{_clean_title(title)} site:cnki.net OR site:cnki.com.cn filetype:pdf'
        
        # Note: This is a simplified approach
        # In production, you'd want to use a proper search API or scraper
        
    except Exception as e:
        print(f"CNKI mirror search failed: {e}")
    
    return pdf_urls


# ============================================================================
# RUSSIA - CyberLeninka
# ============================================================================

def search_cyberleninka(title: str, doi: str = None) -> List[Tuple[str, str]]:
    """
    Search CyberLeninka (Russia) - ENHANCED.
    
    Major Russian OA repository (3M+ papers, ALL FREE PDFs).
    This is a GOLDMINE - every paper has a free PDF!
    CyberLeninka hosts many English-language papers with very permissive access.
    Direct PDF downloads without registration.
    """
    if not title:
        return []
    
    pdf_urls = []
    seen_articles = set()
    
    try:
        # CyberLeninka has a simple search API
        base_url = "https://cyberleninka.ru/api/search"
        
        # Try simpler search endpoint
        search_url = "https://cyberleninka.ru/search"
        params = {'q': _clean_title(title)}
        
        headers = {
            'User-Agent': UA,
            'Accept-Language': 'en,ru;q=0.9',
        }
        
        response = requests.get(search_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for article links - CyberLeninka patterns
        article_patterns = [
            ('a', {'href': re.compile(r'/article/n/[^"]+', re.I)}),
            ('a', {'href': re.compile(r'/article/v/[^"]+', re.I)}),
            ('a', {'class': re.compile(r'.*title.*', re.I)}),
        ]
        
        for tag, attrs in article_patterns:
            for link in soup.find_all(tag, attrs):
                href = link.get('href', '')
                
                # Skip if we've seen this article
                if href in seen_articles:
                    continue
                seen_articles.add(href)
                
                # CyberLeninka article pages
                if '/article/' in href:
                    article_url = urljoin('https://cyberleninka.ru', href)
                    
                    # CyberLeninka PDF pattern is predictable
                    # Article URL: /article/n/some-title
                    # PDF URL: /viewer/some-title/pdf or /article/n/some-title/viewer
                    
                    # Try direct PDF patterns
                    article_id = href.split('/')[-1]
                    pdf_candidates = [
                        f"https://cyberleninka.ru/viewer/{article_id}/pdf",
                        f"https://cyberleninka.ru/article/n/{article_id}/pdf",
                        f"https://cyberleninka.ru/article/n/{article_id}/viewer",
                        article_url.replace('/article/', '/viewer/') + '/pdf',
                    ]
                    
                    pdf_urls.extend(pdf_candidates)
                    
                    # Also try visiting the article page
                    if len(pdf_urls) < 3:  # Only if we need more candidates
                        try:
                            article_response = requests.get(article_url, headers=headers, timeout=10)
                            article_soup = BeautifulSoup(article_response.content, 'html.parser')
                            
                            # Look for download buttons
                            for pdf_link in article_soup.find_all(['a', 'button'], 
                                    class_=re.compile(r'.*(download|pdf|скачать).*', re.I)):
                                href = pdf_link.get('href', '')
                                if href:
                                    pdf_url = urljoin('https://cyberleninka.ru', href)
                                    pdf_urls.append(pdf_url)
                            
                            time.sleep(0.3)  # Be respectful
                            
                        except Exception:
                            continue
        
    except Exception as e:
        print(f"CyberLeninka search failed: {e}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in pdf_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    
    return unique_urls[:8]


# ============================================================================
# IRAN - SID.ir
# ============================================================================

def search_sid_iran(title: str, doi: str = "") -> List[str]:
    """
    Search SID.ir (Scientific Information Database - Iran).
    
    Many English papers are available with open access.
    """
    if not title:
        return []
    
    pdf_urls = []
    
    try:
        base_url = "https://www.sid.ir/en/Journal/SearchPaper.aspx"
        params = {'title': _clean_title(title)}
        
        headers = {'User-Agent': UA}
        
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for PDF download links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if 'pdf' in href.lower() or 'download' in href.lower():
                pdf_url = urljoin('https://www.sid.ir', href)
                pdf_urls.append(pdf_url)
        
    except Exception as e:
        print(f"SID.ir search failed: {e}")
    
    return pdf_urls[:5]


# ============================================================================
# SOUTH KOREA - KISS
# ============================================================================

def search_kiss_korea(title: str, doi: str = "") -> List[str]:
    """
    Search KISS (Korean Studies Information Service System).
    
    Contains many English-language papers with OA.
    """
    if not title:
        return []
    
    pdf_urls = []
    
    try:
        # KISS search endpoint
        base_url = "https://kiss.kstudy.com/search/searchList.asp"
        
        params = {
            'searchStr': _clean_title(title),
            'searchGubun': '0',  # All fields
        }
        
        headers = {
            'User-Agent': UA,
            'Accept-Language': 'ko,en;q=0.9',
        }
        
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for PDF links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if 'pdf' in href.lower() or 'download' in href.lower():
                pdf_url = urljoin('https://kiss.kstudy.com', href)
                pdf_urls.append(pdf_url)
        
    except Exception as e:
        print(f"KISS Korea search failed: {e}")
    
    return pdf_urls[:5]


# ============================================================================
# SPAIN - Dialnet
# ============================================================================

def search_dialnet(title: str, doi: str = "") -> List[str]:
    """
    Search Dialnet (Spanish academic repository).
    
    Strong coverage of humanities and philosophy.
    """
    if not title:
        return []
    
    pdf_urls = []
    
    try:
        base_url = "https://dialnet.unirioja.es/buscar/documentos"
        params = {'querysDismax.DOCUMENTAL_TODO': _clean_title(title)}
        
        headers = {
            'User-Agent': UA,
            'Accept-Language': 'es,en;q=0.9',
        }
        
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for "Acceso al texto completo" (full text access) links
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().lower()
            
            if 'pdf' in href.lower() or 'texto completo' in text or 'descargar' in text:
                pdf_url = urljoin('https://dialnet.unirioja.es', href)
                pdf_urls.append(pdf_url)
        
    except Exception as e:
        print(f"Dialnet search failed: {e}")
    
    return pdf_urls[:5]


# ============================================================================
# FRANCE - HAL
# ============================================================================

def search_hal_france(title: str, doi: str = "") -> List[str]:
    """
    Search HAL (Hyper Articles en Ligne - France).
    
    Massive OA repository with excellent philosophy and humanities coverage.
    Uses the official HAL API for reliable results.
    """
    if not title:
        return []
    
    pdf_urls = []
    
    try:
        # HAL API endpoint
        base_url = "https://api.archives-ouvertes.fr/search/"
        
        # Try DOI first if available, then fall back to title
        if doi:
            params = {
                'q': f'doiId_s:"{doi}"',
                'wt': 'json',
                'fl': 'uri_s,files_s,label_s,title_s',
                'rows': 5,
            }
        else:
            params = {
                'q': f'title_t:"{_clean_title(title)}"',
                'wt': 'json',
                'fl': 'uri_s,files_s,label_s,title_s',
                'rows': 10,
            }
        
        headers = {'User-Agent': UA}
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        docs = data.get('response', {}).get('docs', [])
        
        for doc in docs:
            # Check title similarity if searching by title
            if not doi:
                doc_titles = doc.get('title_s', [])
                if doc_titles:
                    doc_title = doc_titles[0] if isinstance(doc_titles, list) else doc_titles
                    if not _titles_match(title, doc_title, threshold=0.6):
                        continue
            
            # Get file URLs (can be a list or string)
            files = doc.get('files_s', [])
            if isinstance(files, str):
                files = [files]
            
            for file_url in files:
                if file_url.endswith('.pdf'):
                    pdf_urls.append(file_url)
            
            # Also try document URI + /document (standard HAL PDF endpoint)
            uri = doc.get('uri_s')
            if uri:
                pdf_urls.append(f"{uri}/document")
                pdf_urls.append(f"{uri}/file/{uri.split('/')[-1]}.pdf")  # Alternative pattern
        
    except Exception as e:
        print(f"HAL search failed: {e}")
    
    return pdf_urls[:8]


# ============================================================================
# BRAZIL - SciELO
# ============================================================================

def search_scielo(title: str, doi: str = "") -> List[str]:
    """
    Search SciELO (Scientific Electronic Library Online - Brazil/Latin America).
    
    Strong coverage of Latin American research, fully open access.
    Uses SciELO's API for more reliable results.
    """
    if not title:
        return []
    
    pdf_urls = []
    
    try:
        # SciELO has multiple endpoints - try the API first
        if doi:
            # Direct DOI lookup
            api_url = f"https://search.scielo.org/api/v1/article"
            params = {'q': f'doi:"{doi}"', 'lang': 'en', 'count': 5}
        else:
            # Title search
            api_url = f"https://search.scielo.org/api/v1/article"
            params = {'q': f'ti:"{_clean_title(title)}"', 'lang': 'en', 'count': 10}
        
        headers = {'User-Agent': UA, 'Accept': 'application/json'}
        
        # Try API first
        try:
            response = requests.get(api_url, params=params, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                articles = data.get('articles', [])
                
                for article in articles:
                    # Check title match if searching by title
                    if not doi:
                        article_title = article.get('title', '')
                        if not _titles_match(title, article_title, threshold=0.6):
                            continue
                    
                    # Get PDF URLs
                    fulltexts = article.get('fulltexts', {})
                    for lang, urls in fulltexts.items():
                        if isinstance(urls, dict) and 'pdf' in urls:
                            pdf_urls.append(urls['pdf'])
                    
                    # Alternative pattern
                    pid = article.get('pid', '')
                    if pid:
                        # SciELO PDF patterns
                        pdf_urls.append(f"https://www.scielo.br/pdf/{pid}.pdf")
                        pdf_urls.append(f"https://www.scielo.org/pdf/{pid}.pdf")
        except Exception:
            pass
        
        # Fallback to HTML search if API doesn't work
        if not pdf_urls:
            search_url = "https://search.scielo.org/"
            params = {
                'q': _clean_title(title),
                'lang': 'en',
                'count': 10,
                'from': 0,
                'output': 'site',
                'sort': '',
                'format': 'summary',
            }
            
            response = requests.get(search_url, params=params, headers={'User-Agent': UA}, timeout=15)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for article result divs
                for result in soup.find_all(['div', 'article'], class_=re.compile(r'.*(result|item).*', re.I)):
                    # Find PDF links within each result
                    for link in result.find_all('a', href=True):
                        href = link['href']
                        link_text = link.get_text().lower()
                        
                        if ('pdf' in href.lower() or 'pdf' in link_text or 
                            'download' in link_text or 'texto completo' in link_text):
                            
                            if href.startswith('http'):
                                pdf_urls.append(href)
                            elif href.startswith('/'):
                                # Try multiple SciELO domains
                                pdf_urls.append(f"https://www.scielo.br{href}")
                                pdf_urls.append(f"https://www.scielo.org{href}")
        
    except Exception as e:
        print(f"SciELO search failed: {e}")
    
    # Remove duplicates
    seen = set()
    unique_urls = []
    for url in pdf_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    
    return unique_urls[:8]


# ============================================================================
# MASTER SEARCH FUNCTION
# ============================================================================

def search_international_sources(title: str, doi: str = "", countries: List[str] = None) -> List[Tuple[str, str]]:
    """
    Search multiple international academic sources for PDFs.
    
    Args:
        title: Paper title
        doi: DOI (optional)
        countries: List of country codes to search (default: all)
                  Options: 'CN', 'RU', 'IR', 'KR', 'ES', 'FR', 'BR'
    
    Returns:
        List of (source_name, pdf_url) tuples
    """
    if not title:
        return []
    
    # Default to all countries if not specified
    if countries is None:
        countries = ['CN', 'RU', 'IR', 'KR', 'ES', 'FR', 'BR']
    
    results = []
    
    # China
    if 'CN' in countries:
        print("  Searching Baidu Scholar (China)...")
        try:
            urls = search_baidu_scholar(title, doi)
            for url in urls:
                results.append(('Baidu Scholar', url))
        except Exception as e:
            print(f"  Baidu Scholar failed: {e}")
    
    # Russia
    if 'RU' in countries:
        print("  Searching CyberLeninka (Russia)...")
        try:
            urls = search_cyberleninka(title, doi)
            for url in urls:
                results.append(('CyberLeninka', url))
        except Exception as e:
            print(f"  CyberLeninka failed: {e}")
    
    # Iran
    if 'IR' in countries:
        print("  Searching SID.ir (Iran)...")
        try:
            urls = search_sid_iran(title, doi)
            for url in urls:
                results.append(('SID.ir', url))
        except Exception as e:
            print(f"  SID.ir failed: {e}")
    
    # South Korea
    if 'KR' in countries:
        print("  Searching KISS (South Korea)...")
        try:
            urls = search_kiss_korea(title, doi)
            for url in urls:
                results.append(('KISS', url))
        except Exception as e:
            print(f"  KISS failed: {e}")
    
    # Spain
    if 'ES' in countries:
        print("  Searching Dialnet (Spain)...")
        try:
            urls = search_dialnet(title, doi)
            for url in urls:
                results.append(('Dialnet', url))
        except Exception as e:
            print(f"  Dialnet failed: {e}")
    
    # France
    if 'FR' in countries:
        print("  Searching HAL (France)...")
        try:
            urls = search_hal_france(title, doi)
            for url in urls:
                results.append(('HAL', url))
        except Exception as e:
            print(f"  HAL failed: {e}")
    
    # Brazil
    if 'BR' in countries:
        print("  Searching SciELO (Brazil)...")
        try:
            urls = search_scielo(title, doi)
            for url in urls:
                results.append(('SciELO', url))
        except Exception as e:
            print(f"  SciELO failed: {e}")
    
    return results


def try_fetch_from_international_sources(
    title: str,
    doi: str,
    outpath: Path,
    countries: List[str] = None,
    validate_title: bool = True
) -> Optional[str]:
    """
    Try to fetch PDF from international sources with title validation.
    
    Args:
        title: Expected paper title
        doi: Paper DOI
        outpath: Path to save PDF
        countries: List of country codes to search
        validate_title: If True, validate PDF title matches expected title
    
    Returns the source name if successful, None otherwise.
    """
    if not title:
        return None
    
    candidates = search_international_sources(title, doi, countries)
    
    if not candidates:
        return None
    
    print(f"  Found {len(candidates)} international source candidates")
    
    # Try each candidate
    session = requests.Session()
    session.headers.update({'User-Agent': UA})
    
    for source_name, url in candidates:
        try:
            print(f"  Trying {source_name}: {url[:80]}...")
            
            response = session.get(url, timeout=30, allow_redirects=True)
            
            # Check if it's actually a PDF
            if not _validate_pdf_response(response):
                print(f"    ✗ Not a valid PDF")
                continue
            
            # Save to temporary file first
            temp_path = outpath.parent / f"temp_{outpath.name}"
            with temp_path.open('wb') as f:
                f.write(response.content)
            
            # Validate file size
            if temp_path.stat().st_size < 50 * 1024:  # Less than 50KB
                print(f"    ✗ File too small (< 50KB)")
                temp_path.unlink()
                continue
            
            # Validate title if requested
            if validate_title:
                try:
                    # Try to extract title from PDF
                    # First try PyPDF2 if available
                    pdf_text = None
                    try:
                        import PyPDF2
                        with temp_path.open('rb') as f:
                            pdf_reader = PyPDF2.PdfReader(f)
                            if len(pdf_reader.pages) > 0:
                                pdf_text = pdf_reader.pages[0].extract_text()
                    except ImportError:
                        # PyPDF2 not available, try basic text extraction
                        pass
                    
                    # If we got text, validate it
                    if pdf_text:
                        # Check if expected title appears in first page
                        # Use lower threshold for international sources (they might have translations)
                        if not _titles_match(title, pdf_text[:800], threshold=0.5):
                            print(f"    ✗ Title mismatch")
                            print(f"      Expected: '{title[:60]}...'")
                            print(f"      Found in PDF: '{pdf_text[:100]}...'")
                            temp_path.unlink()
                            continue
                        else:
                            print(f"    ✓ Title validated")
                    else:
                        # Could not extract text, accept PDF with warning
                        print(f"    ⚠ Could not validate title (no text extraction), accepting PDF")
                        
                except Exception as e:
                    # If validation fails, accept the PDF anyway
                    print(f"    ⚠ Title validation error: {e}, accepting PDF")
                    pass
            
            # Move to final location
            temp_path.rename(outpath)
            print(f"  ✓ Successfully downloaded from {source_name}")
            return source_name
            
        except Exception as e:
            print(f"  Failed from {source_name}: {e}")
            # Clean up temp file if it exists
            try:
                temp_path = outpath.parent / f"temp_{outpath.name}"
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            continue
    
    return None


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    # Test with a known paper
    test_title = "Emergent Properties of Networks of Biological Signaling Pathways"
    test_doi = "10.1126/science.283.5400.381"
    
    print(f"Testing international sources for: {test_title}\n")
    
    results = search_international_sources(test_title, test_doi)
    
    print(f"\nFound {len(results)} candidates:")
    for source, url in results:
        print(f"  {source}: {url}")
