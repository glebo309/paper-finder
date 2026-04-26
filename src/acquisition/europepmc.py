#!/usr/bin/env python3
"""
Europe PMC acquisition source.

Europe PMC provides access to 3M+ full-text open access articles.
No API key required, no rate limits.

API Documentation: https://europepmc.org/RestfulWebService
"""

import re
import requests
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

from src.core.base_source import SimpleAcquisitionSource
from src.core.result import AcquisitionResult


class EuropePMCSource(SimpleAcquisitionSource):
    """
    Europe PMC - Open access biomedical and life sciences literature.
    
    Coverage: 3M+ full-text articles
    Access: Free API, no rate limits
    Best for: Biomedical, life sciences papers
    """
    
    @property
    def name(self) -> str:
        return "Europe PMC"
    
    def get_download_urls(self, doi: str, metadata: Dict) -> List[str]:
        """
        Query Europe PMC API for full-text PDF URLs.
        
        API endpoint: https://www.ebi.ac.uk/europepmc/webservices/rest/search
        Query format: DOI:"10.1234/example"
        """
        urls = []
        
        try:
            # Search by DOI
            search_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            params = {
                "query": f'DOI:"{doi}"',
                "format": "xml",
                "resultType": "core"
            }
            
            response = self.session.get(search_url, params=params, timeout=15)
            
            if response.status_code != 200:
                return urls
            
            # Parse XML response
            root = ET.fromstring(response.content)
            
            # Check if any results
            hit_count = root.find('.//hitCount')
            if hit_count is None or int(hit_count.text) == 0:
                return urls
            
            # Extract PDF links from results
            for result in root.findall('.//result'):
                # Full-text links
                for link in result.findall('.//fullTextUrlList/fullTextUrl'):
                    url_type = link.find('documentStyle')
                    url_text = link.find('url')
                    
                    if url_type is not None and url_text is not None:
                        doc_style = url_type.text.lower()
                        url_value = url_text.text
                        
                        # Prioritize PDF links
                        if 'pdf' in doc_style and url_value:
                            urls.append(url_value)
                
                # PubMed Central ID - construct direct PDF URL
                pmcid = result.find('.//pmcid')
                if pmcid is not None and pmcid.text:
                    pmc_id = pmcid.text
                    # Remove PMC prefix if present
                    pmc_id = re.sub(r'^PMC', '', pmc_id)
                    pmc_pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/pdf/"
                    if pmc_pdf_url not in urls:
                        urls.append(pmc_pdf_url)
            
            # Try title-based search as fallback
            if not urls and metadata.get('title'):
                title_urls = self._search_by_title(metadata['title'])
                urls.extend(title_urls)
        
        except Exception as e:
            print(f"  Europe PMC API error: {type(e).__name__}")
        
        return urls
    
    def _search_by_title(self, title: str) -> List[str]:
        """Fallback: search by title if DOI search fails."""
        urls = []
        
        try:
            # Clean title for search
            clean_title = re.sub(r'[^\w\s]', ' ', title)
            clean_title = ' '.join(clean_title.split())[:200]  # Limit length
            
            search_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            params = {
                "query": f'TITLE:"{clean_title}"',
                "format": "xml",
                "resultType": "core",
                "pageSize": "3"  # Only check top 3 results
            }
            
            response = self.session.get(search_url, params=params, timeout=15)
            
            if response.status_code != 200:
                return urls
            
            root = ET.fromstring(response.content)
            
            for result in root.findall('.//result'):
                # Get result title for matching
                result_title = result.find('.//title')
                if result_title is not None:
                    result_title_text = result_title.text or ""
                    
                    # Simple similarity check (both titles contain similar words)
                    if self._titles_similar(title, result_title_text):
                        # Extract PDF links
                        for link in result.findall('.//fullTextUrlList/fullTextUrl'):
                            url_type = link.find('documentStyle')
                            url_text = link.find('url')
                            
                            if url_type is not None and url_text is not None:
                                if 'pdf' in url_type.text.lower():
                                    urls.append(url_text.text)
                        
                        # Only use first matching result
                        break
        
        except Exception:
            pass
        
        return urls
    
    def _titles_similar(self, title1: str, title2: str, threshold: float = 0.6) -> bool:
        """Check if two titles are similar enough."""
        # Simple word-based similarity
        words1 = set(re.findall(r'\w+', title1.lower()))
        words2 = set(re.findall(r'\w+', title2.lower()))
        
        # Remove common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with'}
        words1 = words1 - stop_words
        words2 = words2 - stop_words
        
        if not words1 or not words2:
            return False
        
        # Jaccard similarity
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        similarity = intersection / union if union > 0 else 0
        return similarity >= threshold
