#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-language title search.

Translates paper titles to multiple languages and searches international sources.
Significantly improves success rate for papers with non-English versions.
"""

import re
import time
import random
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def translate_title(title: str, target_lang: str) -> Optional[str]:
    """
    Translate title using Google Translate (free API).
    
    Args:
        title: English title
        target_lang: Target language code (zh-CN, ru, ko, ja, es, fr, de)
    
    Returns:
        Translated title or None if failed
    """
    if not title:
        return None
    
    try:
        # Use Google Translate web interface (no API key needed)
        base_url = "https://translate.googleapis.com/translate_a/single"
        params = {
            'client': 'gtx',
            'sl': 'en',
            'tl': target_lang,
            'dt': 't',
            'q': title
        }
        
        headers = {'User-Agent': UA}
        response = requests.get(base_url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None
        
        # Parse response (it's a nested list)
        result = response.json()
        if result and len(result) > 0 and result[0]:
            translated = ''.join([item[0] for item in result[0] if item[0]])
            return translated
        
    except Exception as e:
        pass
    
    return None


def search_with_translated_title(
    title: str,
    target_lang: str,
    search_engine: str = "baidu"
) -> List[Tuple[str, str]]:
    """
    Translate title and search in target language.
    
    Args:
        title: Original English title
        target_lang: Target language (zh-CN, ru, ko, ja)
        search_engine: Search engine to use (baidu, yandex, naver)
    
    Returns:
        List of (url, description) tuples
    """
    results = []
    
    # DISABLED: Translation causes issues and never works
    print(f"    Translation disabled - using original English title only")
    translated = None  # Force skip translation
    
    if not translated:
        print(f"    Translation failed")
        return []
    
    print(f"    Translated: {translated[:80]}...")
    
    # Search based on language
    if target_lang == 'zh-CN' and search_engine == 'baidu':
        results = _search_baidu(translated)
    elif target_lang == 'ru' and search_engine == 'yandex':
        results = _search_yandex(translated)
    elif target_lang == 'ko' and search_engine == 'naver':
        results = _search_naver(translated)
    
    return results


def _search_baidu(query: str) -> List[Tuple[str, str]]:
    """Search Baidu for Chinese papers"""
    results = []
    
    try:
        url = f"https://www.baidu.com/s?wd={quote(query)}+PDF"
        headers = {'User-Agent': UA}
        
        time.sleep(random.uniform(1, 2))
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract search results
        for result in soup.find_all('div', class_='result')[:10]:
            link = result.find('a')
            if link and link.get('href'):
                href = link['href']
                title = link.get_text().strip()
                
                # Filter for academic domains
                if any(domain in href for domain in ['.edu.cn', '.ac.cn', 'cnki.net', 'wanfangdata.com']):
                    results.append((href, title))
        
    except Exception as e:
        pass
    
    return results


def _search_yandex(query: str) -> List[Tuple[str, str]]:
    """Search Yandex for Russian papers"""
    results = []
    
    try:
        url = f"https://yandex.ru/search/?text={quote(query)}+PDF"
        headers = {'User-Agent': UA}
        
        time.sleep(random.uniform(1, 2))
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract search results
        for result in soup.find_all('li', class_='serp-item')[:10]:
            link = result.find('a')
            if link and link.get('href'):
                href = link['href']
                title = link.get_text().strip()
                
                # Filter for academic domains
                if any(domain in href for domain in ['.ru', 'cyberleninka.ru', 'elibrary.ru']):
                    results.append((href, title))
        
    except Exception as e:
        pass
    
    return results


def _search_naver(query: str) -> List[Tuple[str, str]]:
    """Search Naver for Korean papers"""
    results = []
    
    try:
        url = f"https://search.naver.com/search.naver?query={quote(query)}+PDF"
        headers = {'User-Agent': UA}
        
        time.sleep(random.uniform(1, 2))
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract search results
        for result in soup.find_all('li', class_='bx')[:10]:
            link = result.find('a')
            if link and link.get('href'):
                href = link['href']
                title = link.get_text().strip()
                
                # Filter for academic domains
                if any(domain in href for domain in ['.ac.kr', 'kiss.kstudy.com', 'riss.kr']):
                    results.append((href, title))
        
    except Exception as e:
        pass
    
    return results


def try_fetch_with_multilang(
    title: str,
    doi: str,
    outpath: Path,
    languages: List[str] = None
) -> Optional[str]:
    """
    Try to fetch PDF using multi-language search.
    
    Args:
        title: Paper title (English)
        doi: DOI
        outpath: Output path for PDF
        languages: Languages to try (default: zh-CN, ru, ko)
    
    Returns:
        Source type if successful, None otherwise
    """
    if not title:
        return None
    
    if languages is None:
        languages = ['zh-CN', 'ru', 'ko']
    
    print("  Trying multi-language search...")
    
    # Map languages to search engines
    lang_to_engine = {
        'zh-CN': 'baidu',
        'ru': 'yandex',
        'ko': 'naver'
    }
    
    session = requests.Session()
    session.headers.update({'User-Agent': UA})
    
    for lang in languages:
        engine = lang_to_engine.get(lang)
        if not engine:
            continue
        
        print(f"  Searching in {lang}...")
        
        try:
            results = search_with_translated_title(title, lang, engine)
            
            if not results:
                continue
            
            print(f"    Found {len(results)} results")
            
            # Try each result
            for url, desc in results[:5]:  # Top 5 results
                try:
                    # Check if URL points to PDF
                    if url.lower().endswith('.pdf'):
                        response = session.get(url, timeout=30, allow_redirects=True)
                        
                        # Validate PDF
                        if response.content[:4] == b'%PDF' and len(response.content) > 50 * 1024:
                            with outpath.open('wb') as f:
                                f.write(response.content)
                            
                            print(f"  ✓ Downloaded from {lang} search")
                            return f'multilang_{lang}'
                    
                    # Otherwise, try to extract PDF from page
                    else:
                        response = session.get(url, timeout=15)
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.content, 'html.parser')
                            
                            # Look for PDF links
                            for link in soup.find_all('a', href=True):
                                href = link['href']
                                if href.lower().endswith('.pdf') or '/pdf' in href.lower():
                                    # Try to download
                                    pdf_response = session.get(href, timeout=30, allow_redirects=True)
                                    
                                    if pdf_response.content[:4] == b'%PDF' and len(pdf_response.content) > 50 * 1024:
                                        with outpath.open('wb') as f:
                                            f.write(pdf_response.content)
                                        
                                        print(f"  ✓ Downloaded from {lang} search")
                                        return f'multilang_{lang}'
                    
                    time.sleep(random.uniform(1, 2))
                    
                except Exception as e:
                    continue
        
        except Exception as e:
            print(f"    {lang} search failed: {e}")
            continue
    
    return None


if __name__ == "__main__":
    # Test translation
    test_title = "Attention Is All You Need"
    
    print("=" * 80)
    print(f"Testing multi-language translation for: {test_title}")
    print("=" * 80)
    print()
    
    for lang in ['zh-CN', 'ru', 'ko', 'ja']:
        translated = translate_title(test_title, lang)
        print(f"{lang}: {translated}")
