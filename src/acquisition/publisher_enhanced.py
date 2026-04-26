#!/usr/bin/env python3
"""
Enhanced publisher-specific strategies for major commercial publishers.

When Sci-Hub fails and preprints don't exist, exploit publisher-specific patterns.
Each major publisher has quirks that can be leveraged.

Publishers covered:
- Nature/Springer (SharedIt, epdf, author manuscripts)
- Science/AAAS (FirstRelease, author copies)
- Elsevier/Cell (SSRN preprints, Mendeley data)
- Wiley (OnlineOpen, author manuscripts, epdf endpoint)
- IEEE (author preprints, conference proceedings)
- ACS (ChemRxiv preprints, ACS AuthorChoice)
- RSC (gold OA, institutional repos)
- Taylor & Francis (author versions)
- SAGE (SharedIt)
- Oxford/Cambridge (PMC deposits)
"""

import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Optional, Dict, List, Callable
import re
import time
import random
from difflib import SequenceMatcher

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _detect_publisher(publisher: str, doi: str) -> str:
    """Normalize publisher name for strategy selection"""
    if not publisher:
        # Try to infer from DOI
        if doi.startswith('10.1038/') or doi.startswith('10.1007/'):
            return 'springer'
        elif doi.startswith('10.1126/'):
            return 'science'
        elif doi.startswith('10.1016/'):
            return 'elsevier'
        elif doi.startswith('10.1002/'):
            return 'wiley'
        elif doi.startswith('10.1109/'):
            return 'ieee'
        elif doi.startswith('10.1021/'):
            return 'acs'
        elif doi.startswith('10.1039/'):
            return 'rsc'
        return 'unknown'
    
    pub_lower = publisher.lower()
    
    if 'springer' in pub_lower or 'nature' in pub_lower:
        return 'springer'
    elif 'science' in pub_lower or 'aaas' in pub_lower:
        return 'science'
    elif 'elsevier' in pub_lower or 'cell' in pub_lower:
        return 'elsevier'
    elif 'wiley' in pub_lower:
        return 'wiley'
    elif 'ieee' in pub_lower:
        return 'ieee'
    elif 'acs' in pub_lower or 'american chemical' in pub_lower:
        return 'acs'
    elif 'rsc' in pub_lower or 'royal society of chemistry' in pub_lower:
        return 'rsc'
    elif 'taylor' in pub_lower or 'francis' in pub_lower:
        return 'taylor'
    elif 'sage' in pub_lower:
        return 'sage'
    elif 'oxford' in pub_lower or 'oup' in pub_lower:
        return 'oxford'
    elif 'cambridge' in pub_lower:
        return 'cambridge'
    
    return 'unknown'


# ============================================================================
# NATURE / SPRINGER
# ============================================================================

def try_springer_epdf(doi: str, session: requests.Session) -> Optional[str]:
    """
    Try Springer epdf endpoint - sometimes accessible.
    """
    try:
        epdf_url = f"https://link.springer.com/content/pdf/{doi}.pdf"
        response = session.head(epdf_url, timeout=10, allow_redirects=True)
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' in content_type:
                return epdf_url
    except:
        pass
    
    return None


def try_nature_accepted_manuscript(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Nature allows author accepted manuscripts in repositories.
    Search via Europe PMC.
    """
    try:
        search_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        params = {
            'query': f'"{title}" AND SRC:PPR',
            'format': 'json',
            'pageSize': 5
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for result in data.get('resultList', {}).get('result', []):
                pmcid = result.get('pmcid')
                if pmcid:
                    pdf_url = f"https://europepmc.org/articles/{pmcid}?pdf=render"
                    return pdf_url
    except:
        pass
    
    return None


def try_springer_sharedit(doi: str, session: requests.Session) -> Optional[str]:
    """
    Springer SharedIt - free reading links that sometimes provide PDFs.
    """
    try:
        # SharedIt URL patterns
        patterns = [
            f"https://rdcu.be/{doi.split('/')[-1]}",
            f"https://link.springer.com/epdf/{doi}"
        ]
        
        for url in patterns:
            response = session.get(url, timeout=10, allow_redirects=True)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if 'pdf' in href.lower() or 'download' in href.lower():
                        if not href.startswith('http'):
                            href = f"https://link.springer.com{href}"
                        return href
    except:
        pass
    
    return None


# ============================================================================
# SCIENCE / AAAS
# ============================================================================

def try_science_first_release(doi: str, session: requests.Session) -> Optional[str]:
    """
    Science First Release PDFs are sometimes accessible.
    """
    try:
        # Science PDF patterns
        pdf_patterns = [
            f"https://www.science.org/doi/pdf/{doi}",
            f"https://www.sciencemag.org/content/{doi.split('/')[-1]}.full.pdf"
        ]
        
        for pdf_url in pdf_patterns:
            response = session.head(pdf_url, timeout=10, allow_redirects=False)
            if response.status_code == 200:
                return pdf_url
    except:
        pass
    
    return None


def try_science_author_manuscript(title: str, session: requests.Session) -> Optional[str]:
    """
    Science author manuscripts via PMC.
    """
    try:
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {
            'db': 'pmc',
            'term': f'"{title}"[Title] AND science[journal]',
            'retmode': 'json',
            'retmax': 3
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            pmcids = data.get('esearchresult', {}).get('idlist', [])
            
            if pmcids:
                pmcid = pmcids[0]
                pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/pdf/"
                return pdf_url
    except:
        pass
    
    return None


# ============================================================================
# ELSEVIER / CELL
# ============================================================================

def try_elsevier_am(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Elsevier accepted manuscripts via SSRN.
    """
    try:
        search_url = "https://papers.ssrn.com/sol3/results.cfm"
        params = {'txtKeywords': title}
        
        response = session.get(search_url, params=params, timeout=15, headers={'User-Agent': UA})
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                if 'download' in link['href'] and 'pdf' in link['href'].lower():
                    pdf_url = f"https://papers.ssrn.com{link['href']}"
                    return pdf_url
    except:
        pass
    
    return None


def try_elsevier_mendeley_data(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Check Mendeley Data (owned by Elsevier) for supplementary PDFs.
    """
    try:
        search_url = "https://data.mendeley.com/api/search"
        params = {'query': title}
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for item in data.get('items', []):
                files = item.get('files', [])
                for file_info in files:
                    if file_info.get('filename', '').endswith('.pdf'):
                        file_id = file_info.get('id')
                        dataset_id = item.get('id')
                        pdf_url = f"https://data.mendeley.com/datasets/{dataset_id}/files/{file_id}"
                        return pdf_url
    except:
        pass
    
    return None


# ============================================================================
# WILEY
# ============================================================================

def try_wiley_epdf(doi: str, session: requests.Session) -> Optional[str]:
    """
    Wiley epdf endpoint - sometimes works.
    """
    try:
        # Wiley PDF patterns
        pdf_patterns = [
            f"https://onlinelibrary.wiley.com/doi/epdf/{doi}",
            f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}"
        ]
        
        for pdf_url in pdf_patterns:
            response = session.head(pdf_url, timeout=10, allow_redirects=True)
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '').lower()
                if 'pdf' in content_type:
                    return pdf_url
    except:
        pass
    
    return None


def try_wiley_onlineopen(doi: str, session: requests.Session) -> Optional[str]:
    """
    Check if paper is Wiley OnlineOpen (gold OA).
    """
    try:
        landing_url = f"https://onlinelibrary.wiley.com/doi/{doi}"
        response = session.get(landing_url, timeout=15, headers={'User-Agent': UA})
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for OA indicators
            if soup.find(text=re.compile('OnlineOpen', re.I)) or soup.find(class_=re.compile('open-access')):
                # Try to get PDF
                pdf_link = soup.find('a', href=re.compile(r'epdf|pdf', re.I))
                if pdf_link:
                    pdf_url = pdf_link['href']
                    if not pdf_url.startswith('http'):
                        pdf_url = f"https://onlinelibrary.wiley.com{pdf_url}"
                    return pdf_url
    except:
        pass
    
    return None


# ============================================================================
# IEEE
# ============================================================================

def try_ieee_arnumber(doi: str, session: requests.Session) -> Optional[str]:
    """
    IEEE papers - try to get via arnumber (article number).
    """
    try:
        # Extract arnumber from DOI or landing page
        landing_url = f"https://ieeexplore.ieee.org/document/{doi.split('/')[-1]}"
        response = session.get(landing_url, timeout=15, headers={'User-Agent': UA})
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for PDF download
            pdf_link = soup.find('a', href=re.compile(r'stamp|pdf', re.I))
            if pdf_link:
                pdf_url = pdf_link['href']
                if not pdf_url.startswith('http'):
                    pdf_url = f"https://ieeexplore.ieee.org{pdf_url}"
                return pdf_url
    except:
        pass
    
    return None


def try_ieee_conference_proceedings(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    IEEE conference proceedings sometimes have open versions.
    """
    try:
        # Check if it's a conference paper
        if 'conference' in title.lower() or 'proceedings' in title.lower():
            # Search via author homepages (common for conference papers)
            # This is a placeholder - would need author info
            pass
    except:
        pass
    
    return None


# ============================================================================
# ACS
# ============================================================================

def try_acs_authorchoice(doi: str, session: requests.Session) -> Optional[str]:
    """
    ACS AuthorChoice - check if paper is gold OA.
    """
    try:
        landing_url = f"https://pubs.acs.org/doi/{doi}"
        response = session.get(landing_url, timeout=15, headers={'User-Agent': UA})
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Check for AuthorChoice indicator
            if soup.find(text=re.compile('ACS AuthorChoice', re.I)):
                # Try PDF download
                pdf_link = soup.find('a', {'title': re.compile('pdf', re.I)})
                if pdf_link:
                    pdf_url = pdf_link['href']
                    if not pdf_url.startswith('http'):
                        pdf_url = f"https://pubs.acs.org{pdf_url}"
                    return pdf_url
    except:
        pass
    
    return None


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

PUBLISHER_STRATEGIES = {
    'springer': [
        ("Springer ePDF", try_springer_epdf),
        ("SharedIt", try_springer_sharedit),
        ("Accepted Manuscript", try_nature_accepted_manuscript),
    ],
    'science': [
        ("First Release PDF", try_science_first_release),
        ("Author Manuscript", try_science_author_manuscript),
    ],
    'elsevier': [
        ("SSRN Preprint", try_elsevier_am),
        ("Mendeley Data", try_elsevier_mendeley_data),
    ],
    'wiley': [
        ("ePDF Endpoint", try_wiley_epdf),
        ("OnlineOpen", try_wiley_onlineopen),
    ],
    'ieee': [
        ("ARNumber PDF", try_ieee_arnumber),
        ("Conference Proceedings", try_ieee_conference_proceedings),
    ],
    'acs': [
        ("AuthorChoice", try_acs_authorchoice),
    ],
}


def try_fetch_publisher_enhanced(
    doi: str,
    title: str,
    publisher: str,
    output_file: Path,
    session: requests.Session,
    browser_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Main entry point - try publisher-specific strategies.
    """
    pub_type = _detect_publisher(publisher, doi)
    
    if pub_type == 'unknown':
        return False
    
    strategies = PUBLISHER_STRATEGIES.get(pub_type, [])
    
    if not strategies:
        return False
    
    print(f"  🏢 Trying {pub_type.upper()} publisher strategies...")
    
    for strategy_name, strategy_func in strategies:
        try:
            print(f"    → {strategy_name}...")
            
            # Call strategy (handle different signatures)
            if 'title' in strategy_func.__code__.co_varnames:
                pdf_url = strategy_func(doi, title, session)
            else:
                pdf_url = strategy_func(doi, session)
            
            if pdf_url:
                print(f"      Found URL: {pdf_url[:60]}...")
                pdf_resp = session.get(pdf_url, timeout=30, allow_redirects=True, headers={'User-Agent': UA})
                
                if pdf_resp.content.startswith(b'%PDF') and len(pdf_resp.content) > 50*1024:
                    with output_file.open('wb') as f:
                        f.write(pdf_resp.content)
                    print(f"    ✓ Downloaded via {strategy_name}")
                    return True
                else:
                    # For Springer, some "download" URLs return an HTML viewer without raw PDF.
                    # Never count this as a PDF success, but optionally open in browser for reading.
                    opened_in_browser = False
                    if pub_type == 'springer' and browser_callback and isinstance(pdf_url, str):
                        lower_url = pdf_url.lower()
                        # Heuristic: only treat known viewer-style endpoints as potential full-article views.
                        if any(token in lower_url for token in ["/en/download", "/epdf/", "/content/pdf/"]):
                            # Be conservative: require reasonably large HTML and title match.
                            try:
                                if len(pdf_resp.content) > 60 * 1024:
                                    from bs4 import BeautifulSoup
                                    soup = BeautifulSoup(pdf_resp.content, 'html.parser')
                                    page_title = soup.title.get_text(strip=True) if soup.title else ""
                                    if page_title and title:
                                        sim = SequenceMatcher(None, title.lower(), page_title.lower()).ratio()
                                    else:
                                        sim = 0.0
                                    if sim >= 0.6:
                                        print("    ⚠ Found Springer HTML viewer (no raw PDF). Opening in browser for reading...")
                                        try:
                                            browser_callback(pdf_url)
                                            opened_in_browser = True
                                        except Exception as e:
                                            print(f"    ⚠ Browser callback failed: {type(e).__name__}")
                            except Exception:
                                pass
                    if not opened_in_browser:
                        print(f"    ✗ Not a valid PDF")
        
        except Exception as e:
            print(f"    ✗ {strategy_name} failed: {type(e).__name__}")
            continue
    
    return False
