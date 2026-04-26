#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chinese academic deep crawler.

Specialized crawler for Chinese academic sources:
- CNKI (China National Knowledge Infrastructure)
- Wanfang Data
- VIP (维普)
- Chinese university repositories
- Chinese professor homepages
"""

import re
import time
import random
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def search_cnki(title: str, author: str = None, doi: str = None) -> List[Tuple[str, str]]:
    """
    Search CNKI (China National Knowledge Infrastructure) - ENHANCED.
    
    CNKI is the largest Chinese academic database (50M+ papers).
    Now tries multiple search strategies and direct PDF access.
    """
    results = []
    
    try:
        # Strategy 1: Direct DOI search (fastest)
        if doi:
            doi_url = f"https://doi.cnki.net/{doi}"
            try:
                response = requests.get(doi_url, headers={'User-Agent': UA}, timeout=10, allow_redirects=True)
                if response.status_code == 200 and 'cnki.net' in response.url:
                    results.append((response.url, f"CNKI DOI: {doi}"))
            except:
                pass
        
        # Strategy 2: Title search with better parsing
        base_url = "https://kns.cnki.net/kns8/defaultresult/index"
        params = {'kw': title, 'korder': 'SU'}
        headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        
        time.sleep(random.uniform(1, 2))  # Faster
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Multiple selectors for better coverage
            for selector in ['tr.result-table-list', 'div.result-item', 'li.result']:
                for item in soup.select(selector)[:15]:  # More results
                    link = item.find('a', href=True)
                    if link and 'detail' in link['href']:
                        href = link['href']
                        title_text = link.get_text().strip()
                        
                        if not href.startswith('http'):
                            href = urljoin('https://kns.cnki.net', href)
                        
                        # Try to find direct PDF link
                        pdf_link = item.find('a', href=re.compile(r'.*\.pdf$|.*download.*', re.I))
                        if pdf_link:
                            pdf_href = pdf_link['href']
                            if not pdf_href.startswith('http'):
                                pdf_href = urljoin('https://kns.cnki.net', pdf_href)
                            results.append((pdf_href, f"{title_text} [PDF]"))
                        else:
                            results.append((href, title_text))
        
    except Exception as e:
        pass
    
    return results[:20]  # Return more results


def search_wanfang(title: str, author: str = None) -> List[Tuple[str, str]]:
    """
    Search Wanfang Data (万方数据).
    
    Major Chinese academic database.
    """
    results = []
    
    try:
        base_url = "https://s.wanfangdata.com.cn/paper"
        params = {'q': title}
        
        headers = {'User-Agent': UA}
        
        time.sleep(random.uniform(2, 3))
        
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract results
        for item in soup.find_all('div', class_='normal-list')[:10]:
            link = item.find('a', href=True)
            if link:
                href = link['href']
                title_text = link.get_text().strip()
                
                if not href.startswith('http'):
                    href = urljoin('https://s.wanfangdata.com.cn', href)
                
                results.append((href, title_text))
        
    except Exception as e:
        pass
    
    return results


def search_vip(title: str, author: str = None) -> List[Tuple[str, str]]:
    """
    Search VIP (维普资讯).
    
    Another major Chinese academic database.
    """
    results = []
    
    try:
        base_url = "http://www.cqvip.com/main/search.aspx"
        params = {'k': title}
        
        headers = {'User-Agent': UA}
        
        time.sleep(random.uniform(2, 3))
        
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract results
        for item in soup.find_all('div', class_='list')[:10]:
            link = item.find('a', href=True)
            if link:
                href = link['href']
                title_text = link.get_text().strip()
                
                if not href.startswith('http'):
                    href = urljoin('http://www.cqvip.com', href)
                
                results.append((href, title_text))
        
    except Exception as e:
        pass
    
    return results


def search_chinese_universities(title: str, author: str = None) -> List[str]:
    """
    Search Chinese university repositories.
    
    Many Chinese universities have open repositories.
    """
    results = []
    
    # Common Chinese university repository domains
    repo_domains = [
        '.edu.cn',
        'repository',
        'dspace',
        'ir.lib',
        'thesis'
    ]
    
    try:
        # Search Baidu for university repositories
        query = f'"{title}" site:.edu.cn filetype:pdf'
        url = f"https://www.baidu.com/s?wd={quote(query)}"
        
        headers = {'User-Agent': UA}
        
        time.sleep(random.uniform(2, 3))
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract PDF links
        for result in soup.find_all('div', class_='result')[:10]:
            link = result.find('a')
            if link and link.get('href'):
                href = link['href']
                
                # Check if it's a PDF or university link
                if '.pdf' in href.lower() or any(domain in href for domain in repo_domains):
                    results.append(href)
        
    except Exception as e:
        pass
    
    return results


def extract_pdf_from_cnki(page_url: str) -> Optional[str]:
    """
    Extract PDF download link from CNKI page.
    
    CNKI has specific download patterns.
    """
    try:
        headers = {'User-Agent': UA}
        response = requests.get(page_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for download links
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().strip()
            
            # Common CNKI download patterns
            if any(word in text for word in ['下载', 'PDF', 'download']):
                if 'download' in href or 'pdf' in href.lower():
                    return urljoin(page_url, href)
        
        # Check for CAJ/PDF download buttons
        for btn in soup.find_all(['button', 'a'], class_=re.compile('download|btn')):
            onclick = btn.get('onclick', '')
            if 'pdf' in onclick.lower() or 'download' in onclick.lower():
                # Extract URL from onclick
                match = re.search(r'["\']([^"\']*\.pdf[^"\']*)["\']', onclick)
                if match:
                    return urljoin(page_url, match.group(1))
        
    except Exception as e:
        pass
    
    return None


def try_fetch_chinese_sources(
    title: str,
    doi: str,
    outpath: Path,
    author: str = None,
    translated_title: str = None
) -> Optional[str]:
    """
    Try to fetch PDF from Chinese academic sources.
    
    Args:
        title: English title
        doi: DOI
        outpath: Output path
        author: Author name (optional)
        translated_title: Chinese translated title (optional)
    
    Returns:
        Source type if successful, None otherwise
    """
    if not title and not translated_title:
        return None
    
    print("  Searching Chinese academic sources...")
    
    search_title = translated_title if translated_title else title
    
    session = requests.Session()
    session.headers.update({'User-Agent': UA})
    
    # Try CNKI
    print("    Searching CNKI...")
    cnki_results = search_cnki(search_title, author)
    
    if cnki_results:
        print(f"      Found {len(cnki_results)} CNKI results")
        
        for page_url, page_title in cnki_results[:5]:
            try:
                print(f"      Checking: {page_url[:60]}...")
                
                # Try to extract PDF
                pdf_url = extract_pdf_from_cnki(page_url)
                
                if not pdf_url:
                    continue
                
                # Download PDF
                response = session.get(pdf_url, timeout=30, allow_redirects=True)
                
                # Validate
                if response.content[:4] == b'%PDF' and len(response.content) > 50 * 1024:
                    with outpath.open('wb') as f:
                        f.write(response.content)
                    
                    print(f"  ✓ Downloaded from CNKI")
                    return 'cnki'
                
            except Exception as e:
                continue
    
    # Try Wanfang
    print("    Searching Wanfang...")
    wanfang_results = search_wanfang(search_title, author)
    
    if wanfang_results:
        print(f"      Found {len(wanfang_results)} Wanfang results")
        
        for page_url, page_title in wanfang_results[:5]:
            try:
                # Visit page and look for PDF
                response = session.get(page_url, timeout=15)
                
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for PDF links
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    
                    if href.lower().endswith('.pdf') or '/pdf' in href.lower():
                        pdf_url = urljoin(page_url, href)
                        
                        # Try download
                        pdf_response = session.get(pdf_url, timeout=30)
                        
                        if pdf_response.content[:4] == b'%PDF' and len(pdf_response.content) > 50 * 1024:
                            with outpath.open('wb') as f:
                                f.write(pdf_response.content)
                            
                            print(f"  ✓ Downloaded from Wanfang")
                            return 'wanfang'
                
            except Exception as e:
                continue
    
    # Try Chinese university repositories
    print("    Searching Chinese university repositories...")
    uni_urls = search_chinese_universities(search_title, author)
    
    if uni_urls:
        print(f"      Found {len(uni_urls)} university results")
        
        for url in uni_urls[:5]:
            try:
                # If it's a direct PDF link
                if url.lower().endswith('.pdf'):
                    response = session.get(url, timeout=30, allow_redirects=True)
                    
                    if response.content[:4] == b'%PDF' and len(response.content) > 50 * 1024:
                        with outpath.open('wb') as f:
                            f.write(response.content)
                        
                        print(f"  ✓ Downloaded from Chinese university")
                        return 'chinese_university'
                
            except Exception as e:
                continue
    
    return None


if __name__ == "__main__":
    # Test
    test_title = "Deep Learning"
    
    print(f"Testing Chinese sources for: {test_title}")
    print("=" * 80)
    
    cnki_results = search_cnki(test_title)
    print(f"CNKI: {len(cnki_results)} results")
    
    wanfang_results = search_wanfang(test_title)
    print(f"Wanfang: {len(wanfang_results)} results")
