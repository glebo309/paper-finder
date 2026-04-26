#!/usr/bin/env python3
"""
PubMed Central (PMC) acquisition source - REFACTORED EXAMPLE.

This shows how to refactor existing sources to use the new clean architecture.

Compare this with the old implementation in paper_finder.py (lines 2314-2344):
- Old: 30 lines, mixed concerns, returns bool
- New: 50 lines, clean separation, returns AcquisitionResult
- Benefits: testable, reusable, consistent
"""

from pathlib import Path
from typing import Dict, List
from xml.etree import ElementTree as ET

import requests

from src.core.base_source import SimpleAcquisitionSource
from src.core.result import AcquisitionResult


class PubMedCentralSource(SimpleAcquisitionSource):
    """
    Acquire papers from PubMed Central Open Access subset.
    
    Coverage: ~7M full-text articles in biomedical sciences.
    """
    
    @property
    def name(self) -> str:
        return "PubMed Central"
    
    def get_download_urls(self, doi: str, metadata: Dict) -> List[str]:
        """
        Query PMC API to find PDF links.
        
        PMC has an OA service that returns XML with PDF URLs:
        https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=DOI
        """
        urls = []
        
        try:
            # PMC API endpoint
            api_url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={doi}"
            
            response = self.session.get(api_url, timeout=15)
            response.raise_for_status()
            
            # Parse XML response
            root = ET.fromstring(response.content)
            
            # Check for errors
            if root.find('.//error') is not None:
                return []
            
            # Extract PDF links
            for record in root.findall('.//record'):
                for link in record.findall('.//link[@format="pdf"]'):
                    pdf_url = link.get('href')
                    if pdf_url:
                        urls.append(pdf_url)
                        print(f"    Found PMC PDF: {pdf_url[:60]}...")
            
        except Exception as e:
            print(f"    PMC API query failed: {type(e).__name__}")
        
        return urls


# ============================================================================
# USAGE EXAMPLE - How to integrate into pipeline
# ============================================================================

def try_pmc(doi: str, output_file: Path, metadata: Dict, session: requests.Session = None) -> bool:
    """
    Backward-compatible wrapper for existing pipeline.
    
    This allows gradual migration: old code can still use try_pmc() function,
    while new code uses PubMedCentralSource class directly.
    """
    source = PubMedCentralSource(session=session)
    result = source.try_acquire(doi, output_file, metadata)
    
    if result.success:
        print(f"  ✓ Downloaded from {result.source}")
    
    return result.success


# ============================================================================
# TESTING EXAMPLE
# ============================================================================

def test_pmc_source():
    """
    Example unit test using the new architecture.
    
    With the new design, we can:
    1. Mock the HTTP requests easily
    2. Test URL generation separately from download logic
    3. Test validation separately from acquisition
    """
    from unittest.mock import Mock, patch
    from pathlib import Path
    
    # Setup
    source = PubMedCentralSource()
    doi = "10.1371/journal.pone.0123456"
    output_file = Path("/tmp/test.pdf")
    metadata = {"title": "Test Paper"}
    
    # Test 1: URL generation
    with patch.object(source.session, 'get') as mock_get:
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'''<?xml version="1.0"?>
        <OA xmlns="https://www.ncbi.nlm.nih.gov/pmc/oa">
          <records>
            <record>
              <link format="pdf" href="https://pmc.ncbi.nlm.nih.gov/test.pdf"/>
            </record>
          </records>
        </OA>'''
        mock_get.return_value = mock_response
        
        urls = source.get_download_urls(doi, metadata)
        
        assert len(urls) == 1
        assert "test.pdf" in urls[0]
    
    # Test 2: Error handling
    with patch.object(source.session, 'get') as mock_get:
        # Mock error response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'<?xml version="1.0"?><OA><error>Not found</error></OA>'
        mock_get.return_value = mock_response
        
        urls = source.get_download_urls(doi, metadata)
        
        assert len(urls) == 0
    
    print("✓ All tests passed")


if __name__ == "__main__":
    # Run tests
    test_pmc_source()
