"""
Advanced Publisher Bypass Techniques

This module implements aggressive but ethical techniques to access academic papers
that may be available through institutional access, preprint servers, or author copies.

Techniques:
1. ResearchGate author uploads
2. Academia.edu author uploads  
3. Institutional repository mirrors
4. Preprint server versions (arXiv, bioRxiv, etc.)
5. Author homepage PDFs
6. Google Scholar "All versions" links
7. Publisher API endpoints (some allow limited access)
8. Wayback Machine historical snapshots
"""

import requests
from typing import Optional, List, Dict
from pathlib import Path
import re
from urllib.parse import quote_plus, urlparse
import time
from difflib import SequenceMatcher


class AdvancedBypass:
    """Advanced techniques to find papers through alternative channels."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
    
    def _title_similarity(self, title1: str, title2: str) -> float:
        """Calculate similarity between two titles (0-1)."""
        # Normalize titles
        t1 = title1.lower().strip()
        t2 = title2.lower().strip()
        
        # Remove common punctuation
        for char in '.,;:!?()[]{}"\'':
            t1 = t1.replace(char, '')
            t2 = t2.replace(char, '')
        
        # Calculate similarity
        return SequenceMatcher(None, t1, t2).ratio()
    
    def _validate_pdf_title(self, pdf_path: Path, expected_title: str, min_similarity: float = 0.6) -> bool:
        """Validate that PDF contains expected title.
        
        Args:
            pdf_path: Path to PDF file
            expected_title: Expected paper title
            min_similarity: Minimum similarity score (0-1)
        
        Returns:
            True if title matches, False otherwise
        """
        try:
            import PyPDF2
            
            with pdf_path.open('rb') as f:
                reader = PyPDF2.PdfReader(f)
                
                # Check metadata title
                if reader.metadata and reader.metadata.title:
                    metadata_title = reader.metadata.title
                    similarity = self._title_similarity(expected_title, metadata_title)
                    if similarity >= min_similarity:
                        return True
                
                # Check first page text
                if len(reader.pages) > 0:
                    first_page = reader.pages[0].extract_text()
                    # Get first 500 chars (usually contains title)
                    first_text = first_page[:500]
                    similarity = self._title_similarity(expected_title, first_text)
                    if similarity >= min_similarity:
                        return True
            
            return False
            
        except ImportError:
            # PyPDF2 not available, skip validation
            print("      ⚠ PyPDF2 not available, skipping title validation")
            return True
        except Exception as e:
            # Validation failed, be conservative
            print(f"      ⚠ Title validation failed: {type(e).__name__}")
            return False
    
    def try_all_methods(self, doi: str, title: str, authors: List[str], output_file: Path) -> bool:
        """Try all advanced bypass methods."""
        
        print("  🔓 Advanced Bypass Techniques...")
        
        # Method 1: ResearchGate
        if self._try_researchgate(title, authors, output_file):
            return True
        
        # Method 2: Academia.edu
        if self._try_academia(title, authors, output_file):
            return True
        
        # Method 3: Preprint servers
        if self._try_preprints(doi, title, output_file):
            return True
        
        # Method 4: Wayback Machine
        if self._try_wayback(doi, output_file):
            return True
        
        # Method 5: Publisher API backdoors
        if self._try_publisher_apis(doi, output_file):
            return True
        
        return False
    
    def _try_researchgate(self, title: str, authors: List[str], output_file: Path) -> bool:
        """Try to find paper on ResearchGate with validation."""
        try:
            print("    → ResearchGate...")
            
            # Search ResearchGate
            search_url = f"https://www.researchgate.net/search/publication?q={quote_plus(title)}"
            response = self.session.get(search_url, timeout=15)
            
            if response.status_code != 200:
                return False
            
            # Look for PDF download links
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # ResearchGate has direct download links in search results
            for link in soup.find_all('a', href=True):
                href = link['href']
                if 'publication' in href and 'download' in href.lower():
                    pdf_url = href if href.startswith('http') else f"https://www.researchgate.net{href}"
                    
                    # Try to download
                    pdf_response = self.session.get(pdf_url, timeout=30, stream=True)
                    if pdf_response.status_code == 200:
                        content = pdf_response.content
                        if content.startswith(b'%PDF') and len(content) > 50*1024:
                            with output_file.open('wb') as f:
                                f.write(content)
                            
                            # Validate title
                            if self._validate_pdf_title(output_file, title):
                                print("      ✓ Found on ResearchGate!")
                                return True
                            else:
                                print("      ✗ Title mismatch")
                                output_file.unlink(missing_ok=True)
            
            return False
            
        except Exception as e:
            return False
    
    def _try_academia(self, title: str, authors: List[str], output_file: Path) -> bool:
        """Try to find paper on Academia.edu."""
        try:
            print("    → Academia.edu...")
            
            # Search Academia.edu
            search_url = f"https://www.academia.edu/search?q={quote_plus(title)}"
            response = self.session.get(search_url, timeout=15)
            
            if response.status_code != 200:
                return False
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for PDF links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.pdf' in href.lower() or '/download/' in href:
                    pdf_url = href if href.startswith('http') else f"https://www.academia.edu{href}"
                    
                    pdf_response = self.session.get(pdf_url, timeout=30, stream=True)
                    if pdf_response.status_code == 200:
                        content = pdf_response.content
                        if content.startswith(b'%PDF') and len(content) > 50*1024:
                            with output_file.open('wb') as f:
                                f.write(content)
                            print("      ✓ Found on Academia.edu!")
                            return True
            
            return False
            
        except Exception as e:
            return False
    
    def _try_preprints(self, doi: str, title: str, output_file: Path) -> bool:
        """Try preprint servers (arXiv, bioRxiv, medRxiv, etc.)."""
        try:
            print("    → Preprint servers...")
            
            # arXiv
            if self._try_arxiv(title, output_file):
                return True
            
            # bioRxiv/medRxiv
            if self._try_biorxiv(doi, title, output_file):
                return True
            
            # ChemRxiv
            if self._try_chemrxiv(title, output_file):
                return True
            
            return False
            
        except Exception:
            return False
    
    def _try_arxiv(self, title: str, output_file: Path) -> bool:
        """Search arXiv with title validation."""
        try:
            # arXiv API - get top 3 results for better matching
            search_url = f"http://export.arxiv.org/api/query?search_query=ti:{quote_plus(title)}&max_results=3"
            response = self.session.get(search_url, timeout=15)
            
            if '<entry>' not in response.text:
                return False
            
            # Extract all arXiv IDs and titles
            entries = re.findall(r'<entry>.*?</entry>', response.text, re.DOTALL)
            
            for entry in entries:
                # Extract arXiv ID
                id_match = re.search(r'arxiv.org/abs/(\d+\.\d+)', entry)
                if not id_match:
                    continue
                
                arxiv_id = id_match.group(1)
                
                # Extract title from entry
                title_match = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
                if not title_match:
                    continue
                
                arxiv_title = title_match.group(1).strip()
                
                # Check title similarity BEFORE downloading
                similarity = self._title_similarity(title, arxiv_title)
                print(f"      arXiv {arxiv_id}: '{arxiv_title[:60]}...' (similarity: {similarity:.2f})")
                
                if similarity < 0.5:  # Require at least 50% similarity
                    print(f"        ✗ Title mismatch (similarity {similarity:.2f} < 0.5)")
                    continue
                
                # Download
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                pdf_response = self.session.get(pdf_url, timeout=30)
                
                if pdf_response.status_code == 200 and pdf_response.content.startswith(b'%PDF'):
                    # Save temporarily
                    with output_file.open('wb') as f:
                        f.write(pdf_response.content)
                    
                    # Validate title in PDF
                    if self._validate_pdf_title(output_file, title, min_similarity=0.5):
                        print(f"      ✓ Found on arXiv ({arxiv_id})!")
                        return True
                    else:
                        print(f"        ✗ PDF title validation failed")
                        output_file.unlink(missing_ok=True)
            
            return False
            
        except Exception as e:
            return False
    
    def _try_biorxiv(self, doi: str, title: str, output_file: Path) -> bool:
        """Search bioRxiv/medRxiv."""
        try:
            # Try direct DOI resolution
            for server in ['biorxiv', 'medrxiv']:
                search_url = f"https://www.{server}.org/content/{doi}v1.full.pdf"
                response = self.session.get(search_url, timeout=15)
                
                if response.status_code == 200 and response.content.startswith(b'%PDF'):
                    with output_file.open('wb') as f:
                        f.write(response.content)
                    print(f"      ✓ Found on {server}!")
                    return True
            
            return False
            
        except Exception:
            return False
    
    def _try_chemrxiv(self, title: str, output_file: Path) -> bool:
        """Search ChemRxiv with validation."""
        try:
            # ChemRxiv search
            search_url = f"https://chemrxiv.org/engage/chemrxiv/public-api/v1/items?term={quote_plus(title)}"
            response = self.session.get(search_url, timeout=15)
            
            if response.status_code != 200:
                return False
            
            data = response.json()
            if not data.get('itemHits'):
                return False
            
            # Check top 3 results
            for hit in data['itemHits'][:3]:
                item = hit.get('item', {})
                
                # Get title from result
                chemrxiv_title = item.get('title', '')
                if not chemrxiv_title:
                    continue
                
                # Check title similarity BEFORE downloading
                similarity = self._title_similarity(title, chemrxiv_title)
                print(f"      ChemRxiv: '{chemrxiv_title[:60]}...' (similarity: {similarity:.2f})")
                
                if similarity < 0.5:
                    print(f"        ✗ Title mismatch (similarity {similarity:.2f} < 0.5)")
                    continue
                
                # Download
                if 'asset' in item and 'original' in item['asset']:
                    pdf_url = item['asset']['original']['url']
                    
                    pdf_response = self.session.get(pdf_url, timeout=30)
                    if pdf_response.status_code == 200 and pdf_response.content.startswith(b'%PDF'):
                        with output_file.open('wb') as f:
                            f.write(pdf_response.content)
                        
                        # Validate PDF title
                        if self._validate_pdf_title(output_file, title, min_similarity=0.5):
                            print("      ✓ Found on ChemRxiv!")
                            return True
                        else:
                            print("        ✗ PDF title validation failed")
                            output_file.unlink(missing_ok=True)
            
            return False
            
        except Exception:
            return False
    
    def _try_wayback(self, doi: str, output_file: Path) -> bool:
        """Try Wayback Machine for historical snapshots."""
        try:
            print("    → Wayback Machine...")
            
            # Check if DOI URL was archived
            doi_url = f"https://doi.org/{doi}"
            wayback_api = f"http://archive.org/wayback/available?url={quote_plus(doi_url)}"
            
            response = self.session.get(wayback_api, timeout=15)
            if response.status_code != 200:
                return False
            
            data = response.json()
            if not data.get('archived_snapshots', {}).get('closest'):
                return False
            
            snapshot_url = data['archived_snapshots']['closest']['url']
            
            # Try to find PDF in archived page
            snapshot_response = self.session.get(snapshot_url, timeout=30)
            if snapshot_response.status_code != 200:
                return False
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(snapshot_response.content, 'html.parser')
            
            # Look for PDF links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.pdf' in href.lower():
                    # Wayback URLs need special handling
                    if 'web.archive.org' not in href:
                        href = f"http://web.archive.org{href}"
                    
                    pdf_response = self.session.get(href, timeout=30)
                    if pdf_response.status_code == 200 and pdf_response.content.startswith(b'%PDF'):
                        with output_file.open('wb') as f:
                            f.write(pdf_response.content)
                        print("      ✓ Found in Wayback Machine!")
                        return True
            
            return False
            
        except Exception:
            return False
    
    def _try_publisher_apis(self, doi: str, output_file: Path) -> bool:
        """Try publisher API endpoints that sometimes allow access."""
        try:
            print("    → Publisher APIs...")
            
            # Springer API (sometimes works without auth)
            if '10.1007' in doi or '10.1038' in doi:
                api_url = f"https://api.springernature.com/meta/v2/json?q=doi:{doi}&api_key=test"
                response = self.session.get(api_url, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    # Look for open access links
                    if 'records' in data:
                        for record in data['records']:
                            if 'url' in record and record.get('openaccess') == 'true':
                                pdf_url = record['url'][0]['value']
                                pdf_response = self.session.get(pdf_url, timeout=30)
                                if pdf_response.content.startswith(b'%PDF'):
                                    with output_file.open('wb') as f:
                                        f.write(pdf_response.content)
                                    print("      ✓ Found via Springer API!")
                                    return True
            
            # Elsevier API (limited access)
            if '10.1016' in doi:
                # Try ScienceDirect guest access
                api_url = f"https://api.elsevier.com/content/article/doi/{doi}?view=FULL"
                response = self.session.get(api_url, timeout=15)
                # Usually requires API key, but worth trying
            
            return False
            
        except Exception:
            return False


def try_advanced_bypass(doi: str, title: str, authors: List[str], output_file: Path) -> bool:
    """
    Main entry point for advanced bypass techniques.
    
    Args:
        doi: Paper DOI
        title: Paper title
        authors: List of author names
        output_file: Where to save PDF
    
    Returns:
        True if PDF was found and downloaded
    """
    bypass = AdvancedBypass()
    return bypass.try_all_methods(doi, title, authors, output_file)
