#!/usr/bin/env python3
"""
Repository hunting - Zenodo, Figshare, OSF, institutional repositories.

When publishers paywall, researchers often upload to open repositories.
This module hunts these places systematically.

Targets:
- Zenodo (CERN, EU-funded research)
- Figshare (data + papers)
- OSF (Open Science Framework)
- Institutional repositories (.edu, .ac.*, dspace, eprints, handle.net)
- Dataverse (Harvard, others)
"""

import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Optional, List, Dict
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _title_similarity(t1: str, t2: str) -> float:
    """Calculate title similarity (0-1)"""
    if not t1 or not t2:
        return 0.0
    t1 = re.sub(r'[^a-z0-9\s]', '', t1.lower())
    t2 = re.sub(r'[^a-z0-9\s]', '', t2.lower())
    return SequenceMatcher(None, t1, t2).ratio()


def _is_institutional_repo(url: str) -> bool:
    """Check if URL is from an institutional repository"""
    if not url:
        return False
    
    url_lower = url.lower()
    
    # University domains
    tlds = ['.edu', '.ac.uk', '.ac.cn', '.edu.cn', '.ac.jp', '.edu.au', '.ac.in', 
            '.edu.br', '.ac.za', '.edu.sg', '.ac.kr', '.edu.tw']
    
    # Repo keywords
    repo_keywords = ['repository', 'dspace', 'eprints', 'scholarworks', 'digitalcommons',
                     'handle.net', 'pure.', 'research-repository', 'openrepository']
    
    return any(tld in url_lower for tld in tlds) or any(kw in url_lower for kw in repo_keywords)


def try_zenodo(doi: str, title: str, authors: List[str], session: requests.Session) -> Optional[str]:
    """
    Search Zenodo - CERN's open repository.
    Huge collection, especially EU-funded and physics research.
    """
    try:
        print("    → Zenodo...")
        
        # Zenodo API search
        search_url = "https://zenodo.org/api/records"
        params = {
            'q': title,
            'size': 10,
            'sort': 'bestmatch'
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        for hit in data.get('hits', {}).get('hits', []):
            metadata = hit.get('metadata', {})
            item_title = metadata.get('title', '')
            
            similarity = _title_similarity(title, item_title)
            if similarity < 0.7:
                continue
            
            # Validate authors if available
            if authors:
                item_authors = [a.get('name', '') for a in metadata.get('creators', [])]
                author_match = False
                for provided_author in authors[:2]:
                    author_last = provided_author.split()[-1].lower()
                    for item_author in item_authors:
                        if author_last in item_author.lower():
                            author_match = True
                            break
                    if author_match:
                        break
                
                if not author_match and similarity < 0.85:
                    continue
            
            # Get PDF file
            files = hit.get('files', [])
            for file_info in files:
                if file_info.get('type') == 'pdf' or file_info.get('key', '').endswith('.pdf'):
                    pdf_url = file_info.get('links', {}).get('self')
                    if pdf_url:
                        print(f"      ✓ Found on Zenodo (similarity: {similarity:.2f})")
                        return pdf_url
        
    except Exception as e:
        print(f"      ✗ Zenodo error: {type(e).__name__}")
    
    return None


def try_figshare(doi: str, title: str, authors: List[str], session: requests.Session) -> Optional[str]:
    """
    Search Figshare - data and publication repository.
    """
    try:
        print("    → Figshare...")
        
        # Figshare API search
        search_url = "https://api.figshare.com/v2/articles/search"
        payload = {
            'search_for': title,
            'page_size': 10
        }
        
        response = session.post(search_url, json=payload, timeout=15, headers={'Content-Type': 'application/json'})
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        for item in data:
            item_title = item.get('title', '')
            similarity = _title_similarity(title, item_title)
            
            if similarity < 0.7:
                continue
            
            # Validate authors
            if authors:
                item_authors = [a.get('full_name', '') for a in item.get('authors', [])]
                author_match = False
                for provided_author in authors[:2]:
                    author_last = provided_author.split()[-1].lower()
                    for item_author in item_authors:
                        if author_last in item_author.lower():
                            author_match = True
                            break
                    if author_match:
                        break
                
                if not author_match and similarity < 0.85:
                    continue
            
            # Get PDF file
            files = item.get('files', [])
            for file_info in files:
                if file_info.get('is_link_only'):
                    continue
                
                name = file_info.get('name', '').lower()
                if name.endswith('.pdf'):
                    # Get article detail for download URL
                    article_id = item.get('id')
                    detail_url = f"https://api.figshare.com/v2/articles/{article_id}"
                    detail_resp = session.get(detail_url, timeout=10)
                    
                    if detail_resp.status_code == 200:
                        detail = detail_resp.json()
                        for f in detail.get('files', []):
                            if f.get('name', '').lower().endswith('.pdf'):
                                pdf_url = f.get('download_url')
                                if pdf_url:
                                    print(f"      ✓ Found on Figshare (similarity: {similarity:.2f})")
                                    return pdf_url
        
    except Exception as e:
        print(f"      ✗ Figshare error: {type(e).__name__}")
    
    return None


def try_osf_storage(doi: str, title: str, authors: List[str], session: requests.Session) -> Optional[str]:
    """
    Search OSF (Open Science Framework) - project storage and registrations.
    Different from OSF Preprints - this searches project files.
    """
    try:
        print("    → OSF Storage...")
        
        # OSF search API (different from preprints)
        search_url = "https://api.osf.io/v2/search/"
        params = {
            'q': title,
            'filter[category]': 'project,registration'
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        for item in data.get('data', []):
            attrs = item.get('attributes', {})
            item_title = attrs.get('title', '')
            
            similarity = _title_similarity(title, item_title)
            if similarity < 0.7:
                continue
            
            # Get project files
            project_id = item.get('id')
            files_url = f"https://api.osf.io/v2/nodes/{project_id}/files/"
            
            files_resp = session.get(files_url, timeout=10)
            if files_resp.status_code == 200:
                files_data = files_resp.json()
                
                for file_item in files_data.get('data', []):
                    file_attrs = file_item.get('attributes', {})
                    file_name = file_attrs.get('name', '').lower()
                    
                    if file_name.endswith('.pdf'):
                        # Get download link
                        links = file_item.get('links', {})
                        download_url = links.get('download')
                        if download_url:
                            print(f"      ✓ Found on OSF (similarity: {similarity:.2f})")
                            return download_url
        
    except Exception as e:
        print(f"      ✗ OSF error: {type(e).__name__}")
    
    return None


def try_dataverse(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Search Harvard Dataverse and other Dataverse installations.
    Often has supplementary materials and author copies.
    """
    try:
        print("    → Dataverse...")
        
        # Harvard Dataverse search API
        search_url = "https://dataverse.harvard.edu/api/search"
        params = {
            'q': title,
            'type': 'file',
            'per_page': 10
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        for item in data.get('data', {}).get('items', []):
            item_name = item.get('name', '')
            
            # Check if it's a PDF with similar name
            if item_name.lower().endswith('.pdf'):
                # Get file ID and construct download URL
                file_id = item.get('file_id')
                if file_id:
                    # Dataverse download URL format
                    pdf_url = f"https://dataverse.harvard.edu/api/access/datafile/{file_id}"
                    print(f"      ✓ Found on Dataverse")
                    return pdf_url
        
    except Exception as e:
        print(f"      ✗ Dataverse error: {type(e).__name__}")
    
    return None


def try_institutional_repo_hunt(doi: str, title: str, authors: List[str], session: requests.Session) -> Optional[str]:
    """
    Hunt institutional repositories by leveraging:
    1. Author email domains from Crossref
    2. Google Scholar institutional links
    3. CORE institutional results
    """
    try:
        print("    → Institutional repositories...")
        
        # Get author affiliations from Crossref
        crossref_url = f"https://api.crossref.org/works/{doi}"
        crossref_resp = session.get(crossref_url, timeout=10)
        
        if crossref_resp.status_code == 200:
            crossref_data = crossref_resp.json().get('message', {})
            
            # Extract institutional domains
            institutions = set()
            for author in crossref_data.get('author', []):
                for affiliation in author.get('affiliation', []):
                    aff_name = affiliation.get('name', '').lower()
                    # Extract domain-like patterns
                    if 'university' in aff_name or 'institute' in aff_name:
                        institutions.add(aff_name)
            
            # If we have institutions, search their repositories
            if institutions:
                # Search CORE for institutional repos
                for inst in list(institutions)[:3]:  # Top 3
                    search_url = "https://core.ac.uk:443/api-v2/search"
                    params = {
                        'q': f'"{title}" {inst}',
                        'page': 1,
                        'pageSize': 5
                    }
                    
                    core_resp = session.get(search_url, params=params, timeout=10)
                    if core_resp.status_code == 200:
                        core_data = core_resp.json()
                        
                        for item in core_data.get('data', []):
                            item_title = item.get('title', '')
                            similarity = _title_similarity(title, item_title)
                            
                            if similarity >= 0.7:
                                download_url = item.get('downloadUrl')
                                if download_url and _is_institutional_repo(download_url):
                                    print(f"      ✓ Found in institutional repo (similarity: {similarity:.2f})")
                                    return download_url
        
    except Exception as e:
        print(f"      ✗ Institutional hunt error: {type(e).__name__}")
    
    return None


def try_dspace_eprints_generic(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Search common DSpace and EPrints installations globally.
    These are the most common institutional repo platforms.
    """
    try:
        print("    → DSpace/EPrints generic search...")
        
        # Use Google to find papers in dspace/eprints
        # This is a fallback - requires careful rate limiting
        import time
        import random
        
        time.sleep(random.uniform(2, 4))
        
        search_url = "https://www.google.com/search"
        params = {
            'q': f'"{title}" (site:dspace OR site:eprints) filetype:pdf',
            'num': 5
        }
        
        response = session.get(
            search_url, 
            params=params, 
            timeout=15,
            headers={'User-Agent': UA}
        )
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Parse Google results (simple extraction)
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '/url?q=' in href and '.pdf' in href:
                    # Extract actual URL
                    url_match = re.search(r'/url\?q=([^&]+)', href)
                    if url_match:
                        pdf_url = url_match.group(1)
                        if _is_institutional_repo(pdf_url):
                            print(f"      ✓ Found in DSpace/EPrints")
                            return pdf_url
        
    except Exception as e:
        print(f"      ✗ DSpace/EPrints error: {type(e).__name__}")
    
    return None


def try_fetch_from_repositories(
    doi: str,
    title: str,
    authors: List[str],
    output_file: Path,
    session: requests.Session
) -> bool:
    """
    Main entry point - systematically hunt repositories.
    
    Priority:
    1. Zenodo (huge, reliable API)
    2. Figshare (good API, lots of data)
    3. OSF Storage (project files)
    4. Institutional repos (author affiliations)
    5. Dataverse (supplementary materials)
    6. Generic DSpace/EPrints hunt (fallback)
    """
    print("  🏛️ Hunting open repositories...")
    
    strategies = [
        ("Zenodo", lambda: try_zenodo(doi, title, authors, session)),
        ("Figshare", lambda: try_figshare(doi, title, authors, session)),
        ("OSF Storage", lambda: try_osf_storage(doi, title, authors, session)),
        ("Institutional Repos", lambda: try_institutional_repo_hunt(doi, title, authors, session)),
        ("Dataverse", lambda: try_dataverse(doi, title, session)),
        ("DSpace/EPrints", lambda: try_dspace_eprints_generic(doi, title, session)),
    ]
    
    for strategy_name, strategy_func in strategies:
        try:
            pdf_url = strategy_func()
            
            if pdf_url:
                print(f"    Downloading from {strategy_name}...")
                pdf_resp = session.get(
                    pdf_url, 
                    timeout=30, 
                    allow_redirects=True,
                    headers={'User-Agent': UA}
                )
                
                if pdf_resp.content.startswith(b'%PDF') and len(pdf_resp.content) > 50*1024:
                    with output_file.open('wb') as f:
                        f.write(pdf_resp.content)
                    print(f"    ✓ Downloaded from {strategy_name}")
                    return True
                else:
                    print(f"    ✗ Not a valid PDF")
        
        except Exception as e:
            print(f"    ✗ {strategy_name} failed: {type(e).__name__}")
            continue
    
    return False
