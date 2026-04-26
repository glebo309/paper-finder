#!/usr/bin/env python3
"""
CORE.ac.uk acquisition source.

CORE aggregates 200M+ open access research papers from repositories worldwide.
API requires free registration: https://core.ac.uk/services/api

Environment variable: CORE_API_KEY
"""

import os
import re
import requests
from pathlib import Path
from typing import Dict, List, Optional

from src.core.base_source import SimpleAcquisitionSource
from src.core.result import AcquisitionResult


class CORESource(SimpleAcquisitionSource):
    """
    CORE.ac.uk - World's largest aggregator of open access research papers.
    
    Coverage: 200M+ papers from 10,000+ repositories
    Access: Free API (requires registration)
    Best for: Repository papers, preprints, theses
    """
    
    def __init__(self, session: requests.Session = None, api_key: str = None):
        super().__init__(session)
        # Get API key from parameter or environment
        self.api_key = api_key or os.getenv('CORE_API_KEY')
    
    @property
    def name(self) -> str:
        return "CORE.ac.uk"
    
    def get_download_urls(self, doi: str, metadata: Dict) -> List[str]:
        """
        Query CORE API for full-text PDF URLs.
        
        API v3 endpoint: https://api.core.ac.uk/v3/search/works
        Requires API key in Authorization header
        """
        if not self.api_key:
            # Silently skip if no API key configured
            return []
        
        urls = []
        
        try:
            # Search by DOI
            search_url = "https://api.core.ac.uk/v3/search/works"
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            params = {
                "q": f'doi:"{doi}"',
                "limit": 5
            }
            
            response = self.session.get(
                search_url,
                headers=headers,
                params=params,
                timeout=15
            )
            
            if response.status_code == 401:
                print(f"  CORE API: Invalid or missing API key")
                return urls
            
            if response.status_code != 200:
                return urls
            
            data = response.json()
            results = data.get('results', [])
            
            if not results:
                # Fallback to title search
                if metadata.get('title'):
                    return self._search_by_title(metadata['title'])
                return urls
            
            # Extract download URLs from results
            for result in results:
                # Direct download URL
                download_url = result.get('downloadUrl')
                if download_url and download_url.endswith('.pdf'):
                    urls.append(download_url)
                
                # Full-text links
                links = result.get('links', [])
                for link in links:
                    link_type = link.get('type', '').lower()
                    link_url = link.get('url', '')
                    
                    if 'download' in link_type and link_url:
                        if link_url.endswith('.pdf') or 'pdf' in link_url.lower():
                            urls.append(link_url)
                
                # Repository URL (may redirect to PDF)
                repo_url = result.get('sourceFulltextUrls', [])
                if repo_url:
                    for url in repo_url:
                        if url and 'pdf' in url.lower():
                            urls.append(url)
        
        except Exception as e:
            print(f"  CORE API error: {type(e).__name__}")
        
        return urls
    
    def _search_by_title(self, title: str) -> List[str]:
        """Fallback: search by title if DOI search fails."""
        if not self.api_key:
            return []
        
        urls = []
        
        try:
            # Clean title for search
            clean_title = re.sub(r'[^\w\s]', ' ', title)
            clean_title = ' '.join(clean_title.split())[:200]
            
            search_url = "https://api.core.ac.uk/v3/search/works"
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            params = {
                "q": f'title:"{clean_title}"',
                "limit": 3  # Only check top 3 results
            }
            
            response = self.session.get(
                search_url,
                headers=headers,
                params=params,
                timeout=15
            )
            
            if response.status_code != 200:
                return urls
            
            data = response.json()
            results = data.get('results', [])
            
            for result in results:
                result_title = result.get('title', '')
                
                # Check title similarity
                if self._titles_similar(title, result_title):
                    # Extract download URL
                    download_url = result.get('downloadUrl')
                    if download_url and download_url.endswith('.pdf'):
                        urls.append(download_url)
                    
                    # Only use first matching result
                    break
        
        except Exception:
            pass
        
        return urls
    
    def _titles_similar(self, title1: str, title2: str, threshold: float = 0.6) -> bool:
        """Check if two titles are similar enough."""
        words1 = set(re.findall(r'\w+', title1.lower()))
        words2 = set(re.findall(r'\w+', title2.lower()))
        
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with'}
        words1 = words1 - stop_words
        words2 = words2 - stop_words
        
        if not words1 or not words2:
            return False
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        similarity = intersection / union if union > 0 else 0
        return similarity >= threshold
