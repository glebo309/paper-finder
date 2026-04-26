#!/usr/bin/env python3
"""
Publisher detection and URL pattern generation.

Handles publisher-specific logic for accessing papers:
- Detecting publisher from URL or DOI
- Generating alternative URLs based on publisher patterns
- Building custom headers required by publishers
"""

import re
from typing import List, Dict, Optional
from urllib.parse import urlparse


class PublisherUtils:
    """
    Utilities for publisher-specific paper acquisition.
    
    Supports major publishers: Springer, Elsevier, Wiley, IEEE, ACS,
    Taylor & Francis, SAGE, Oxford, Cambridge, MDPI, Frontiers, and more.
    """
    
    # Publisher detection patterns
    PUBLISHER_PATTERNS = {
        'springer': ['springer.com', 'nature.com', 'link.springer.com'],
        'elsevier': ['elsevier.com', 'sciencedirect.com'],
        'wiley': ['wiley.com', 'onlinelibrary.wiley.com'],
        'ieee': ['ieee.org', 'ieeexplore.ieee.org'],
        'acs': ['acs.org', 'pubs.acs.org'],
        'taylorfrancis': ['tandfonline.com', 'taylorandfrancis.com'],
        'sage': ['sagepub.com', 'journals.sagepub.com'],
        'oxford': ['oxford.com', 'oup.com', 'academic.oup.com'],
        'cambridge': ['cambridge.org'],
        'mdpi': ['mdpi.com'],
        'frontiers': ['frontiersin.org'],
        'plos': ['plos.org', 'journals.plos.org'],
        'bmc': ['biomedcentral.com', 'bmcbioinformatics.com'],
        'aaas': ['science.org', 'sciencemag.org'],
        'cell': ['cell.com', 'thecellpress.com'],
        'aaai': ['aaai.org'],
        'acm': ['acm.org', 'dl.acm.org'],
    }
    
    # Publisher-specific URL patterns for PDF access
    PDF_PATTERNS = {
        'springer': [
            '{base}/content/pdf/{doi_path}.pdf',
            '{base}/article/{doi_path}/pdf',
            '{article_url}.pdf',
            '{article_url}/pdf',
        ],
        'elsevier': [
            '{article_url}/pdfft',
            '{article_url}/pdf',
            'https://www.sciencedirect.com/science/article/pii/{pii}/pdfft',
        ],
        'wiley': [
            '{article_url}/pdf',
            '{article_url}/pdfdirect',
            '{article_url}/epdf',
        ],
        'ieee': [
            'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}',
            'https://ieeexplore.ieee.org/ielx7/{arnumber}/pdf',
        ],
        'acs': [
            '{article_url}/pdf',
            '{article_url.replace("/doi/", "/doi/pdf/")}',
            '{article_url.replace("/doi/", "/doi/pdfdirect/")}',
            '{article_url.replace("/doi/", "/doi/pdfplus/")}',
        ],
        'mdpi': [
            '{article_url.replace("/htm", "/pdf")}',
            '{article_url}/pdf',
        ],
        'frontiers': [
            '{article_url}/pdf',
            '{article_url}/full',
        ],
    }
    
    def __init__(self):
        """Initialize publisher utilities."""
        pass
    
    def detect_publisher(self, url: str = None, doi: str = None) -> str:
        """
        Detect publisher from URL or DOI.
        
        Args:
            url: Article URL
            doi: DOI string
        
        Returns:
            Publisher name (lowercase) or 'unknown'
        """
        if not url and not doi:
            return 'unknown'
        
        # Try URL-based detection first (most reliable)
        if url:
            url_lower = url.lower()
            
            for publisher, patterns in self.PUBLISHER_PATTERNS.items():
                if any(pattern in url_lower for pattern in patterns):
                    return publisher
        
        # Try DOI-based detection
        if doi:
            doi_lower = doi.lower()
            
            # Springer: 10.1007, 10.1038 (Nature)
            if doi_lower.startswith('10.1007') or doi_lower.startswith('10.1038'):
                return 'springer'
            
            # Elsevier: 10.1016
            elif doi_lower.startswith('10.1016'):
                return 'elsevier'
            
            # Wiley: 10.1002, 10.1111
            elif doi_lower.startswith('10.1002') or doi_lower.startswith('10.1111'):
                return 'wiley'
            
            # IEEE: 10.1109
            elif doi_lower.startswith('10.1109'):
                return 'ieee'
            
            # ACS: 10.1021
            elif doi_lower.startswith('10.1021'):
                return 'acs'
            
            # AAAS (Science): 10.1126
            elif doi_lower.startswith('10.1126'):
                return 'aaas'
            
            # Cell Press: 10.1016/j.cell
            elif 'cell' in doi_lower:
                return 'cell'
            
            # PLOS: 10.1371
            elif doi_lower.startswith('10.1371'):
                return 'plos'
            
            # MDPI: 10.3390
            elif doi_lower.startswith('10.3390'):
                return 'mdpi'
            
            # Frontiers: 10.3389
            elif doi_lower.startswith('10.3389'):
                return 'frontiers'
        
        return 'unknown'
    
    def generate_publisher_urls(
        self,
        doi: str,
        article_url: str = None,
        publisher: str = None
    ) -> List[str]:
        """
        Generate list of potential PDF URLs based on publisher patterns.
        
        Args:
            doi: DOI string
            article_url: Article landing page URL (optional)
            publisher: Publisher name (if known, otherwise will detect)
        
        Returns:
            List of URLs to try (in priority order)
        """
        if not publisher:
            publisher = self.detect_publisher(url=article_url, doi=doi)
        
        urls = []
        
        # Standard DOI resolver
        if doi:
            urls.append(f"https://doi.org/{doi}")
        
        # Publisher-specific patterns
        if publisher in self.PDF_PATTERNS:
            patterns = self.PDF_PATTERNS[publisher]
            
            for pattern in patterns:
                try:
                    # Build URL from pattern
                    url = self._apply_pattern(pattern, doi, article_url, publisher)
                    if url and url not in urls:
                        urls.append(url)
                except:
                    continue
        
        # Generic fallbacks
        if article_url:
            # Try appending /pdf
            pdf_url = article_url.rstrip('/') + '/pdf'
            if pdf_url not in urls:
                urls.append(pdf_url)
            
            # Try replacing /article/ with /content/pdf/
            if '/article/' in article_url:
                pdf_url = article_url.replace('/article/', '/content/pdf/') + '.pdf'
                if pdf_url not in urls:
                    urls.append(pdf_url)
        
        return urls
    
    def _apply_pattern(
        self,
        pattern: str,
        doi: str,
        article_url: str,
        publisher: str
    ) -> Optional[str]:
        """
        Apply a URL pattern template to generate a specific URL.
        
        Args:
            pattern: URL pattern with placeholders
            doi: DOI string
            article_url: Article URL
            publisher: Publisher name
        
        Returns:
            Generated URL or None if pattern cannot be applied
        """
        # Extract base URL from article_url
        base = None
        if article_url:
            parsed = urlparse(article_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
        
        # Extract DOI path (after the registrant prefix)
        doi_path = doi.replace('/', '-') if doi else None
        
        # Publisher-specific extractions
        pii = None
        arnumber = None
        
        if publisher == 'elsevier' and article_url:
            # Extract PII from URL: /science/article/pii/S0123456789
            match = re.search(r'/pii/([A-Z0-9]+)', article_url)
            if match:
                pii = match.group(1)
        
        if publisher == 'ieee' and article_url:
            # Extract arnumber from URL: arnumber=1234567
            match = re.search(r'arnumber[=/](\d+)', article_url)
            if match:
                arnumber = match.group(1)
        
        # Replace placeholders
        url = pattern
        
        # Simple string replacements
        if '{base}' in url and base:
            url = url.replace('{base}', base)
        if '{doi_path}' in url and doi_path:
            url = url.replace('{doi_path}', doi_path)
        if '{article_url}' in url and article_url:
            url = url.replace('{article_url}', article_url)
        if '{pii}' in url and pii:
            url = url.replace('{pii}', pii)
        if '{arnumber}' in url and arnumber:
            url = url.replace('{arnumber}', arnumber)
        
        # Check if all placeholders were replaced
        if '{' in url or '}' in url:
            return None
        
        return url
    
    def get_publisher_headers(
        self,
        publisher: str,
        referer: str = None
    ) -> Dict[str, str]:
        """
        Get custom HTTP headers for publisher-specific requests.
        
        Args:
            publisher: Publisher name
            referer: Referer URL (optional)
        
        Returns:
            Dictionary of HTTP headers
        """
        # Base headers (used by all publishers)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/pdf,application/octet-stream,text/html,application/xhtml+xml,*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
        }
        
        # Add referer if provided
        if referer:
            headers['Referer'] = referer
        
        # Publisher-specific headers
        if publisher == 'springer':
            headers['Upgrade-Insecure-Requests'] = '1'
        
        elif publisher == 'wiley':
            headers['Sec-Fetch-Dest'] = 'document'
            headers['Sec-Fetch-Mode'] = 'navigate'
            headers['Sec-Fetch-Site'] = 'same-origin'
        
        elif publisher == 'elsevier':
            headers['Accept'] = 'application/pdf,*/*'
        
        elif publisher == 'ieee':
            headers['Accept'] = 'application/pdf,image/webp,*/*'
        
        elif publisher == 'acs':
            # ACS sometimes checks for specific Accept header
            headers['Accept'] = 'application/pdf,application/octet-stream,*/*;q=0.8'
        
        return headers
    
    def get_landing_page_url(self, doi: str) -> str:
        """
        Get the standard landing page URL for a DOI.
        
        Args:
            doi: DOI string
        
        Returns:
            Landing page URL
        """
        return f"https://doi.org/{doi}"
    
    def extract_doi_from_url(self, url: str) -> Optional[str]:
        """
        Extract DOI from a URL.
        
        Args:
            url: URL that may contain a DOI
        
        Returns:
            DOI string or None
        """
        # Pattern 1: doi.org URL
        match = re.search(r'doi\.org/(10\.\d{4,}/[^\s\'"<>&]+)', url, re.IGNORECASE)
        if match:
            doi = match.group(1)
            # Clean trailing punctuation/query params
            doi = re.split(r'[?#]', doi)[0]
            doi = re.sub(r'[.,;)\]]+$', '', doi)
            return doi
        
        # Pattern 2: /doi/ in path
        match = re.search(r'/doi/(10\.\d{4,}/[^\s\'"<>&]+)', url, re.IGNORECASE)
        if match:
            doi = match.group(1)
            doi = re.split(r'[?#]', doi)[0]
            doi = re.sub(r'[.,;)\]]+$', '', doi)
            return doi
        
        return None
    
    def is_open_access_publisher(self, publisher: str) -> bool:
        """
        Check if a publisher is known to be open access.
        
        Args:
            publisher: Publisher name
        
        Returns:
            True if publisher is OA by default
        """
        oa_publishers = {
            'mdpi',
            'frontiers',
            'plos',
            'bmc',
            'hindawi',
            'elife',
            'peerj',
        }
        
        return publisher.lower() in oa_publishers


# Singleton instance
_publisher_utils = None


def get_publisher_utils() -> PublisherUtils:
    """Get singleton PublisherUtils instance."""
    global _publisher_utils
    if _publisher_utils is None:
        _publisher_utils = PublisherUtils()
    return _publisher_utils
