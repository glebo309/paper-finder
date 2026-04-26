#!/usr/bin/env python3
"""
Publisher-specific acquisition strategies.

Different publishers have different access patterns:
- Elsevier: SSRN preprints, author manuscripts
- Wiley: Author accepted manuscripts, OnlineOpen
- Taylor & Francis: Author versions, institutional repos
- IEEE: Author preprints, conference papers
- SAGE: SharedIt links
"""

import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Optional, List
import time
import random

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def try_elsevier_ssrn(title: str, session: requests.Session) -> Optional[str]:
    """
    Elsevier owns SSRN - many papers have preprints there.
    """
    try:
        search_url = "https://papers.ssrn.com/sol3/results.cfm"
        params = {'txtKeywords': title}
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for PDF links
            for link in soup.find_all('a', href=True):
                if 'download' in link['href'] and 'pdf' in link['href'].lower():
                    return f"https://papers.ssrn.com{link['href']}"
    except:
        pass
    
    return None


def try_wiley_author_manuscript(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Wiley allows author manuscripts - search institutional repos.
    """
    try:
        # Search Europe PMC for author manuscripts
        search_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        params = {
            'query': f'"{title}" AND SRC:PPR',  # PPR = preprints
            'format': 'json',
            'pageSize': 5
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for result in data.get('resultList', {}).get('result', []):
                # Look for full text links
                if result.get('hasTextMinedTerms') == 'Y':
                    pmcid = result.get('pmcid')
                    if pmcid:
                        pdf_url = f"https://europepmc.org/articles/{pmcid}?pdf=render"
                        return pdf_url
    except:
        pass
    
    return None


def try_ieee_author_preprint(title: str, doi: str, session: requests.Session) -> Optional[str]:
    """
    IEEE allows author preprints - search arXiv and institutional repos.
    """
    try:
        # Many IEEE papers have arXiv preprints
        import urllib.parse
        
        search_url = "http://export.arxiv.org/api/query"
        params = {
            'search_query': f'ti:"{title}"',
            'max_results': 5
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            # Parse arXiv XML
            from xml.etree import ElementTree as ET
            root = ET.fromstring(response.content)
            
            for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
                pdf_link = entry.find('{http://www.w3.org/2005/Atom}link[@title="pdf"]')
                if pdf_link is not None:
                    return pdf_link.get('href')
    except:
        pass
    
    return None


def try_taylor_francis_author_version(title: str, session: requests.Session) -> Optional[str]:
    """
    Taylor & Francis - search for author accepted manuscripts.
    """
    try:
        # Search CORE for T&F author manuscripts
        search_url = "https://core.ac.uk:443/api-v2/search"
        params = {
            'q': f'"{title}" "author accepted manuscript"',
            'page': 1,
            'pageSize': 5
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for item in data.get('data', []):
                download_url = item.get('downloadUrl')
                if download_url and download_url.endswith('.pdf'):
                    return download_url
    except:
        pass
    
    return None


def try_sage_sharedit(doi: str, session: requests.Session) -> Optional[str]:
    """
    SAGE has SharedIt links similar to Springer.
    """
    try:
        # SAGE SharedIt format
        sharedit_url = f"https://journals.sagepub.com/doi/reader/{doi}"
        
        response = session.get(sharedit_url, timeout=10, allow_redirects=True)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for PDF download
            for link in soup.find_all('a', href=True):
                if 'pdf' in link['href'].lower():
                    href = link['href']
                    if not href.startswith('http'):
                        href = f"https://journals.sagepub.com{href}"
                    return href
    except:
        pass
    
    return None


def try_oup_author_manuscript(title: str, session: requests.Session) -> Optional[str]:
    """
    Oxford University Press - search for author manuscripts.
    """
    try:
        # Search PubMed Central for OUP papers
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {
            'db': 'pmc',
            'term': f'"{title}"[Title]',
            'retmode': 'json',
            'retmax': 5
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            pmcids = data.get('esearchresult', {}).get('idlist', [])
            
            if pmcids:
                # Try to get PDF from first result
                pmcid = pmcids[0]
                pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/pdf/"
                return pdf_url
    except:
        pass
    
    return None


PUBLISHER_STRATEGIES = {
    'elsevier': [try_elsevier_ssrn],
    'wiley': [try_wiley_author_manuscript],
    'ieee': [try_ieee_author_preprint],
    'taylor': [try_taylor_francis_author_version],
    'francis': [try_taylor_francis_author_version],
    'sage': [try_sage_sharedit],
    'oxford': [try_oup_author_manuscript],
    'oup': [try_oup_author_manuscript],
}


def try_publisher_specific(publisher: str, doi: str, title: str, output_file: Path, session: requests.Session) -> bool:
    """
    Try publisher-specific strategies based on detected publisher.
    """
    if not publisher:
        return False
    
    publisher_lower = publisher.lower()
    
    # Find matching strategies
    strategies = []
    for key, funcs in PUBLISHER_STRATEGIES.items():
        if key in publisher_lower:
            strategies.extend(funcs)
    
    if not strategies:
        return False
    
    print(f"  📚 Trying {len(strategies)} {publisher} strategy(ies)...")
    
    for strategy_func in strategies:
        try:
            strategy_name = strategy_func.__name__.replace('try_', '').replace('_', ' ').title()
            print(f"    → {strategy_name}...")
            
            # Call strategy (some take different args)
            if 'doi' in strategy_func.__code__.co_varnames:
                result = strategy_func(title, doi, session) if 'title' in strategy_func.__code__.co_varnames else strategy_func(doi, session)
            else:
                result = strategy_func(title, session)
            
            if result:
                print(f"      Found: {result[:60]}...")
                pdf_resp = session.get(result, timeout=30)
                
                if pdf_resp.content.startswith(b'%PDF') and len(pdf_resp.content) > 50*1024:
                    with output_file.open('wb') as f:
                        f.write(pdf_resp.content)
                    print(f"    ✓ Downloaded via {strategy_name}")
                    return True
        except Exception as e:
            continue
    
    return False
