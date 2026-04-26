#!/usr/bin/env python3
"""
Auto-update Sci-Hub working domains.

Checks multiple sources to find currently working Sci-Hub mirrors:
1. Sci-Hub's official status page
2. Wikipedia's Sci-Hub article (lists current domains)
3. Manual domain testing
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Set
import time
import json
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def get_scihub_from_wikipedia() -> List[str]:
    """
    Scrape current Sci-Hub domains from Wikipedia.
    Wikipedia usually has up-to-date list of working mirrors.
    """
    domains = []
    try:
        url = "https://en.wikipedia.org/wiki/Sci-Hub"
        response = requests.get(url, headers={'User-Agent': UA}, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for URLs in the article - ONLY sci-hub domains!
            for link in soup.find_all('a', href=True):
                href = link['href']
                # Must contain sci-hub AND be a full URL
                if 'sci-hub' in href.lower() and href.startswith('http'):
                    # Clean up the URL
                    if '://' in href:
                        domain = href.split('://')[0] + '://' + href.split('://')[1].split('/')[0]
                        # Double-check it's actually a sci-hub domain
                        if 'sci-hub' in domain.lower() and domain not in domains:
                            domains.append(domain)
    except:
        pass
    
    return domains


def get_scihub_from_reddit() -> List[str]:
    """
    Check r/scihub for current working domains.
    Community usually posts updates when domains change.
    """
    domains = []
    try:
        # Reddit's JSON API
        url = "https://www.reddit.com/r/scihub.json"
        headers = {'User-Agent': UA}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Search post titles and text for sci-hub URLs
            for post in data.get('data', {}).get('children', []):
                post_data = post.get('data', {})
                title = post_data.get('title', '').lower()
                selftext = post_data.get('selftext', '').lower()
                
                # Look for domain mentions
                import re
                for text in [title, selftext]:
                    matches = re.findall(r'https?://[a-z0-9-]+\.sci-hub\.[a-z]{2,}', text)
                    domains.extend(matches)
    except:
        pass
    
    return list(set(domains))


def test_scihub_domain(domain: str) -> bool:
    """
    Test if a Sci-Hub domain is working.
    Uses a known DOI to test.
    """
    try:
        # Test with a well-known paper
        test_doi = "10.1126/science.169.3946.635"  # Famous 1970 paper
        url = f"{domain}/{test_doi}"
        
        response = requests.get(url, headers={'User-Agent': UA}, timeout=10, allow_redirects=True)
        
        # Check if we got a valid response (not blocked/down)
        if response.status_code == 200:
            # Check if it's actually Sci-Hub (not a redirect to error page)
            if 'sci-hub' in response.url.lower() or 'pdf' in response.headers.get('content-type', '').lower():
                return True
    except:
        pass
    
    return False


def get_working_scihub_domains() -> List[str]:
    """
    Get list of currently working Sci-Hub domains.
    Combines multiple sources and tests each domain.
    """
    print("🔍 Searching for working Sci-Hub domains...")
    
    # Known domains to always try
    known_domains = [
        "https://sci-hub.se",
        "https://sci-hub.st",
        "https://sci-hub.ru",
        "https://sci-hub.wf",
        "https://sci-hub.ee",
        "https://sci-hub.tf",
        "https://sci-hub.ren",
        "https://sci-hub.shop",
        "https://sci-hub.hkvisa.net",
        "https://sci-hub.mksa.top",
        "https://sci-hub.et-fine.com",
    ]
    
    # Get domains from Wikipedia
    print("  → Checking Wikipedia...")
    wiki_domains = get_scihub_from_wikipedia()
    
    # Get domains from Reddit
    print("  → Checking r/scihub...")
    reddit_domains = get_scihub_from_reddit()
    
    # Combine all sources
    all_domains = list(set(known_domains + wiki_domains + reddit_domains))
    print(f"  Found {len(all_domains)} potential domains")
    
    # Test each domain
    working_domains = []
    print("  → Testing domains...")
    
    for domain in all_domains:
        print(f"    Testing {domain}...", end=' ')
        if test_scihub_domain(domain):
            print("✓ WORKING")
            working_domains.append(domain)
        else:
            print("✗ down")
        time.sleep(0.5)  # Be nice to servers
    
    print(f"\n✅ Found {len(working_domains)} working domains")
    return working_domains


def save_scihub_domains(domains: List[str], cache_file: Path = None):
    """
    Save working domains to cache file.
    """
    if cache_file is None:
        cache_file = Path.home() / '.scihub_domains.json'
    
    data = {
        'domains': domains,
        'updated': time.time()
    }
    
    with cache_file.open('w') as f:
        json.dump(data, f, indent=2)
    
    print(f"💾 Saved to {cache_file}")


def load_scihub_domains(cache_file: Path = None, max_age_hours: int = 24, silent: bool = False) -> List[str]:
    """
    Load cached domains if recent enough, otherwise update.
    
    Args:
        silent: If True, skip update if cache is old (for GUI fast startup)
    """
    if cache_file is None:
        cache_file = Path.home() / '.scihub_domains.json'
    
    # Check if cache exists and is recent
    if cache_file.exists():
        try:
            with cache_file.open('r') as f:
                data = json.load(f)
            
            age_hours = (time.time() - data['updated']) / 3600
            
            if age_hours < max_age_hours:
                if not silent:
                    print(f"📦 Using cached domains (updated {age_hours:.1f}h ago)")
                return data['domains']
            else:
                if silent:
                    # In silent mode, use old cache rather than blocking
                    return data['domains']
                else:
                    print(f"⏰ Cache expired ({age_hours:.1f}h old), updating...")
        except:
            pass
    
    # If no cache and silent mode, return default list
    if silent:
        return [
            "https://sci-hub.se",  # .se is very reliable - prioritize it
            "https://sci-hub.st",
            "https://sci-hub.ru",
            "https://sci-hub.wf",
            "https://sci-hub.ee",
            "https://sci-hub.ren",
        ]
    
    # Update domains
    domains = get_working_scihub_domains()
    save_scihub_domains(domains, cache_file)
    return domains


if __name__ == '__main__':
    # Test the updater
    domains = get_working_scihub_domains()
    print(f"\nWorking Sci-Hub domains:")
    for domain in domains:
        print(f"  - {domain}")
    
    # Save to cache
    save_scihub_domains(domains)
