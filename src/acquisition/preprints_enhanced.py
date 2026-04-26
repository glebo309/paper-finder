#!/usr/bin/env python3
"""
Comprehensive preprint & author version acquisition.

Targets all major preprint servers + uses Crossref relations to find author versions.
This is THE module for when paywalled papers have legal preprint/postprint versions.

Servers covered:
- arXiv (physics, math, CS, quant-bio, econ)
- bioRxiv (biology)
- medRxiv (medical)
- chemRxiv (chemistry)
- SSRN (social sciences, econ, law)
- OSF Preprints (multidisciplinary)
- PsyArXiv (psychology)
- SocArXiv (social sciences)
- RePEc (economics)
- HAL (French national archive)
- Europe PMC (author manuscripts)
- CORE (200M+ OA aggregator)
"""

import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Optional, Dict, List
import re
from difflib import SequenceMatcher

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _title_similarity(t1: str, t2: str) -> float:
    """Calculate title similarity (0-1)"""
    if not t1 or not t2:
        return 0.0
    t1 = re.sub(r'[^a-z0-9\s]', '', t1.lower())
    t2 = re.sub(r'[^a-z0-9\s]', '', t2.lower())
    return SequenceMatcher(None, t1, t2).ratio()


def try_arxiv(doi: str, title: str, authors: List[str], session: requests.Session) -> Optional[str]:
    """
    Search arXiv - the gold standard for physics, math, CS, quant-bio, econ.
    
    Strategy:
    1. Search by title
    2. Validate with author names if available
    3. Return PDF URL
    """
    try:
        print("    → arXiv...")
        
        # arXiv API search
        search_url = "http://export.arxiv.org/api/query"
        params = {
            'search_query': f'ti:"{title}"',
            'max_results': 10
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code != 200:
            return None
        
        # Parse Atom XML
        from xml.etree import ElementTree as ET
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        root = ET.fromstring(response.content)
        
        for entry in root.findall('atom:entry', ns):
            # Get entry title
            entry_title_elem = entry.find('atom:title', ns)
            if entry_title_elem is None:
                continue
            
            entry_title = entry_title_elem.text.strip().replace('\n', ' ')
            similarity = _title_similarity(title, entry_title)
            
            if similarity < 0.6:
                continue
            
            # Validate authors if provided
            if authors:
                entry_authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns)]
                author_match = False
                for provided_author in authors[:3]:  # Check first 3
                    author_last = provided_author.split()[-1].lower()
                    for entry_author in entry_authors:
                        if author_last in entry_author.lower():
                            author_match = True
                            break
                    if author_match:
                        break
                
                if not author_match and similarity < 0.8:
                    continue
            
            # Get PDF link
            for link in entry.findall('atom:link', ns):
                if link.get('title') == 'pdf':
                    pdf_url = link.get('href')
                    print(f"      ✓ Found on arXiv (similarity: {similarity:.2f})")
                    return pdf_url
        
    except Exception as e:
        print(f"      ✗ arXiv error: {type(e).__name__}")
    
    return None


def try_biorxiv_medrxiv(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Try bioRxiv and medRxiv - biology and medical preprints.
    
    These servers often have the same paper before journal publication.
    """
    for server in ["biorxiv", "medrxiv"]:
        try:
            print(f"    → {server}...")
            
            # Search by DOI first (fast)
            search_url = f"https://www.{server}.org/search/{doi}"
            response = session.get(search_url, timeout=15, headers={'User-Agent': UA})
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for PDF link
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if '.full.pdf' in href or ('/content/' in href and 'pdf' in href.lower()):
                        if not href.startswith('http'):
                            href = f"https://www.{server}.org{href}"
                        print(f"      ✓ Found on {server}")
                        return href
            
            # If DOI fails, try title search
            if title:
                search_url = f"https://www.{server}.org/search/{title}"
                response = session.get(search_url, timeout=15, headers={'User-Agent': UA})
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Find results
                    for article in soup.find_all('div', class_='highwire-article-citation'):
                        article_title = article.find('span', class_='highwire-cite-title')
                        if article_title:
                            similarity = _title_similarity(title, article_title.text)
                            if similarity >= 0.7:
                                # Found match, get PDF
                                pdf_link = article.find('a', class_='pdf')
                                if pdf_link:
                                    href = pdf_link['href']
                                    if not href.startswith('http'):
                                        href = f"https://www.{server}.org{href}"
                                    print(f"      ✓ Found on {server} (similarity: {similarity:.2f})")
                                    return href
        
        except Exception as e:
            print(f"      ✗ {server} error: {type(e).__name__}")
            continue
    
    return None


def try_chemrxiv(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Try ChemRxiv - chemistry preprints.
    """
    try:
        print("    → ChemRxiv...")
        
        # ChemRxiv API
        search_url = "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items"
        params = {'term': title, 'limit': 10}
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for item in data.get('itemHits', []):
                item_title = item.get('title', '')
                similarity = _title_similarity(title, item_title)
                
                if similarity >= 0.7:
                    # Get PDF URL from item
                    item_id = item.get('id')
                    if item_id:
                        pdf_url = f"https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/{item_id}/original/content.pdf"
                        print(f"      ✓ Found on ChemRxiv (similarity: {similarity:.2f})")
                        return pdf_url
        
    except Exception as e:
        print(f"      ✗ ChemRxiv error: {type(e).__name__}")
    
    return None


def try_ssrn(doi: str, title: str, authors: List[str], session: requests.Session) -> Optional[str]:
    """
    Try SSRN - social sciences, economics, law preprints.
    Owned by Elsevier but has lots of open preprints.
    """
    try:
        print("    → SSRN...")
        
        search_url = "https://papers.ssrn.com/sol3/results.cfm"
        params = {'txtKeywords': title}
        
        response = session.get(search_url, params=params, timeout=15, headers={'User-Agent': UA})
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for result titles
            for result in soup.find_all('div', class_='title'):
                result_title = result.get_text(strip=True)
                similarity = _title_similarity(title, result_title)
                
                if similarity >= 0.7:
                    # Find download link
                    link = result.find('a', href=True)
                    if link:
                        paper_url = link['href']
                        # Follow to paper page to get PDF
                        paper_resp = session.get(f"https://papers.ssrn.com{paper_url}", timeout=15)
                        if paper_resp.status_code == 200:
                            paper_soup = BeautifulSoup(paper_resp.content, 'html.parser')
                            pdf_link = paper_soup.find('a', href=re.compile(r'download.*\.pdf'))
                            if pdf_link:
                                pdf_url = pdf_link['href']
                                if not pdf_url.startswith('http'):
                                    pdf_url = f"https://papers.ssrn.com{pdf_url}"
                                print(f"      ✓ Found on SSRN (similarity: {similarity:.2f})")
                                return pdf_url
        
    except Exception as e:
        print(f"      ✗ SSRN error: {type(e).__name__}")
    
    return None


def try_osf_preprints(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Try OSF Preprints - multidisciplinary preprint service.
    Includes PsyArXiv, SocArXiv, etc.
    """
    try:
        print("    → OSF Preprints...")
        
        # OSF API
        search_url = "https://api.osf.io/v2/preprints/"
        params = {'filter[title]': title}
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for item in data.get('data', []):
                attrs = item.get('attributes', {})
                item_title = attrs.get('title', '')
                similarity = _title_similarity(title, item_title)
                
                if similarity >= 0.7:
                    # Get links
                    links = item.get('links', {})
                    preprint_doi = attrs.get('doi')
                    
                    # Try to construct PDF URL
                    if preprint_doi:
                        # OSF PDF pattern
                        osf_id = item.get('id')
                        pdf_url = f"https://osf.io/{osf_id}/download"
                        print(f"      ✓ Found on OSF (similarity: {similarity:.2f})")
                        return pdf_url
        
    except Exception as e:
        print(f"      ✗ OSF error: {type(e).__name__}")
    
    return None


def try_europe_pmc(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Try Europe PMC - biomedical author manuscripts.
    Often has accepted author versions before final publication.
    """
    try:
        print("    → Europe PMC...")
        
        search_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        params = {
            'query': f'"{title}"',
            'format': 'json',
            'pageSize': 10
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for result in data.get('resultList', {}).get('result', []):
                result_title = result.get('title', '')
                similarity = _title_similarity(title, result_title)
                
                if similarity >= 0.7:
                    # Check if full text available
                    pmcid = result.get('pmcid')
                    if pmcid:
                        pdf_url = f"https://europepmc.org/articles/{pmcid}?pdf=render"
                        print(f"      ✓ Found on Europe PMC (similarity: {similarity:.2f})")
                        return pdf_url
        
    except Exception as e:
        print(f"      ✗ Europe PMC error: {type(e).__name__}")
    
    return None


def try_hal(doi: str, title: str, authors: List[str], session: requests.Session) -> Optional[str]:
    """
    Try HAL - French national open archive.
    Large collection of European research outputs.
    """
    try:
        print("    → HAL...")
        
        search_url = "https://api.archives-ouvertes.fr/search/"
        params = {
            'q': f'title_t:"{title}"',
            'wt': 'json',
            'rows': 10
        }
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for doc in data.get('response', {}).get('docs', []):
                doc_title = doc.get('title_s', [''])[0]
                similarity = _title_similarity(title, doc_title)
                
                if similarity >= 0.7:
                    # Get PDF URL
                    file_urls = doc.get('fileMain_s')
                    if file_urls:
                        pdf_url = file_urls if isinstance(file_urls, str) else file_urls[0]
                        print(f"      ✓ Found on HAL (similarity: {similarity:.2f})")
                        return pdf_url
        
    except Exception as e:
        print(f"      ✗ HAL error: {type(e).__name__}")
    
    return None


def try_core_aggregator(doi: str, title: str, session: requests.Session) -> Optional[str]:
    """
    Try CORE - aggregates 200M+ OA papers from repos worldwide.
    """
    try:
        print("    → CORE aggregator...")
        
        search_url = "https://core.ac.uk:443/api-v2/search"
        params = {'q': title, 'page': 1, 'pageSize': 10}
        
        response = session.get(search_url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            for item in data.get('data', []):
                item_title = item.get('title', '')
                similarity = _title_similarity(title, item_title)
                
                if similarity >= 0.7:
                    download_url = item.get('downloadUrl')
                    if download_url and download_url.endswith('.pdf'):
                        print(f"      ✓ Found on CORE (similarity: {similarity:.2f})")
                        return download_url
        
    except Exception as e:
        print(f"      ✗ CORE error: {type(e).__name__}")
    
    return None


def try_crossref_preprint_relations(doi: str, session: requests.Session) -> Optional[str]:
    """
    Use Crossref metadata to find preprint relationships.
    Crossref now tracks is-preprint-of / has-preprint relations.
    """
    try:
        print("    → Crossref preprint relations...")
        
        url = f"https://api.crossref.org/works/{doi}"
        response = session.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json().get('message', {})
            
            # Check relation field
            relations = data.get('relation', {})
            
            # Look for preprint relations
            for rel_type in ['is-preprint-of', 'has-preprint', 'is-version-of']:
                for item in relations.get(rel_type, []):
                    preprint_doi = item.get('id')
                    if preprint_doi:
                        print(f"      Found preprint DOI: {preprint_doi}")
                        # Try to resolve preprint DOI
                        preprint_url = f"https://doi.org/{preprint_doi}"
                        return preprint_url  # Let the resolver handle it
        
    except Exception as e:
        print(f"      ✗ Crossref relations error: {type(e).__name__}")
    
    return None


def try_fetch_from_preprints_enhanced(
    doi: str, 
    title: str, 
    authors: List[str],
    output_file: Path,
    session: requests.Session
) -> bool:
    """
    Main entry point - try all preprint servers in priority order.
    
    Priority:
    1. Crossref preprint relations (direct link)
    2. arXiv (huge, well-maintained)
    3. bioRxiv/medRxiv (bio/med)
    4. Europe PMC (author manuscripts)
    5. ChemRxiv (chemistry)
    6. SSRN (social sciences)
    7. OSF/PsyArXiv/SocArXiv (multidisciplinary)
    8. HAL (European)
    9. CORE (aggregator - last resort)
    """
    print("  📄 Searching preprint servers & author versions...")
    
    strategies = [
        ("Crossref Relations", lambda: try_crossref_preprint_relations(doi, session)),
        ("arXiv", lambda: try_arxiv(doi, title, authors, session)),
        ("bioRxiv/medRxiv", lambda: try_biorxiv_medrxiv(doi, title, session)),
        ("Europe PMC", lambda: try_europe_pmc(doi, title, session)),
        ("ChemRxiv", lambda: try_chemrxiv(doi, title, session)),
        ("SSRN", lambda: try_ssrn(doi, title, authors, session)),
        ("OSF Preprints", lambda: try_osf_preprints(doi, title, session)),
        ("HAL", lambda: try_hal(doi, title, authors, session)),
        ("CORE", lambda: try_core_aggregator(doi, title, session)),
    ]
    
    for strategy_name, strategy_func in strategies:
        try:
            pdf_url = strategy_func()
            
            if pdf_url:
                print(f"    Downloading from {strategy_name}...")
                pdf_resp = session.get(pdf_url, timeout=30, allow_redirects=True, headers={'User-Agent': UA})
                
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
