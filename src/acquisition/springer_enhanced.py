#!/usr/bin/env python3
"""
Enhanced Springer/Nature acquisition strategies.

Springer is tricky - they have multiple access points:
1. SharedIt links (free reading, sometimes PDF)
2. Author manuscripts (institutional repos)
3. ResearchGate/Academia uploads
4. Chapter preview PDFs
"""

import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Optional, Dict
import re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def try_springer_sharedit(doi: str, session: requests.Session) -> Optional[str]:
    """
    Try Springer SharedIt links - free reading links.
    Sometimes these provide PDF access.
    """
    try:
        # SharedIt URL format
        sharedit_url = f"https://rdcu.be/{doi.replace('10.1007/', '')}"
        response = session.get(sharedit_url, timeout=10, allow_redirects=True)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for PDF download link
            for link in soup.find_all('a', href=True):
                if 'pdf' in link['href'].lower() or 'download' in link['href'].lower():
                    return link['href']
    except:
        pass
    
    return None


def try_springer_preview(doi: str, session: requests.Session) -> Optional[bytes]:
    """
    Try to get Springer chapter preview.
    Some chapters have preview PDFs available.
    """
    try:
        # Springer preview API
        chapter_id = doi.split('/')[-1]
        preview_url = f"https://link.springer.com/content/pdf/preview/{doi}.pdf"
        
        response = session.get(preview_url, timeout=15)
        if response.status_code == 200 and response.content.startswith(b'%PDF'):
            # Check if it's a real preview (>100KB) not just a stub
            if len(response.content) > 100 * 1024:
                return response.content
    except:
        pass
    
    return None


def try_springer_author_manuscript(title: str, doi: str, session: requests.Session) -> Optional[str]:
    """
    Search for author manuscript versions in institutional repositories.
    Springer allows authors to post manuscripts.
    """
    try:
        # Search CORE for author manuscripts
        search_url = "https://core.ac.uk:443/api-v2/search"
        params = {
            'q': f'"{title}" author manuscript',
            'page': 1,
            'pageSize': 10
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for item in data.get('data', []):
                # Look for institutional repo PDFs
                download_url = item.get('downloadUrl')
                if download_url and download_url.endswith('.pdf'):
                    # Check if it's from a university/institution
                    if any(domain in download_url for domain in ['.edu', '.ac.', 'repository', 'eprints']):
                        return download_url
    except:
        pass
    
    return None


def try_springer_researchgate_direct(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Direct ResearchGate search for Springer papers.
    Many authors upload their Springer chapters.
    """
    try:
        # ResearchGate search by DOI
        search_url = f"https://www.researchgate.net/search/publication?q={doi}"
        headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        
        response = session.get(search_url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for PDF download links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if 'publication' in href and any(x in href for x in ['download', 'pdf', 'fulltext']):
                    if href.startswith('/'):
                        href = f"https://www.researchgate.net{href}"
                    return href
    except:
        pass
    
    return None


def try_springer_google_scholar_pdf(title: str, session: requests.Session) -> Optional[str]:
    """
    Search Google Scholar specifically for PDF versions.
    Filter for institutional repos and author pages.
    """
    try:
        import time
        import random
        
        # Google Scholar search with PDF filter
        search_url = "https://scholar.google.com/scholar"
        params = {
            'q': f'"{title}" filetype:pdf',
            'hl': 'en'
        }
        
        headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        
        time.sleep(random.uniform(2, 4))  # Avoid blocking
        
        response = session.get(search_url, params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for PDF links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.endswith('.pdf') and any(domain in href for domain in ['.edu', '.ac.', 'researchgate', 'academia']):
                    return href
    except:
        pass
    
    return None


def try_fetch_springer_enhanced(doi: str, title: str, output_file: Path, session: requests.Session) -> bool:
    """
    Try all Springer-specific strategies.
    """
    print("  🔬 Trying Springer-specific strategies...")
    
    strategies = [
        ("SharedIt", lambda: try_springer_sharedit(doi, session)),
        ("Preview PDF", lambda: try_springer_preview(doi, session)),
        ("Author Manuscript", lambda: try_springer_author_manuscript(title, doi, session)),
        ("ResearchGate Direct", lambda: try_springer_researchgate_direct(doi, title, session)),
        ("Google Scholar PDF", lambda: try_springer_google_scholar_pdf(title, session)),
    ]
    
    for strategy_name, strategy_func in strategies:
        try:
            print(f"    → {strategy_name}...")
            result = strategy_func()
            
            if result:
                # If bytes (preview), write directly
                if isinstance(result, bytes):
                    with output_file.open('wb') as f:
                        f.write(result)
                    
                    # Validate
                    if output_file.stat().st_size > 50 * 1024:
                        print(f"    ✓ Got PDF via {strategy_name}")
                        return True
                    else:
                        output_file.unlink(missing_ok=True)
                
                # If URL, download
                elif isinstance(result, str):
                    print(f"      Found: {result[:60]}...")
                    pdf_resp = session.get(result, timeout=30)
                    
                    if pdf_resp.content.startswith(b'%PDF') and len(pdf_resp.content) > 50*1024:
                        with output_file.open('wb') as f:
                            f.write(pdf_resp.content)
                        print(f"    ✓ Downloaded via {strategy_name}")
                        return True
        except Exception as e:
            print(f"      ✗ {strategy_name} failed: {type(e).__name__}")
            continue
    
    return False
