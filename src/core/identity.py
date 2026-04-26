#!/usr/bin/env python3
"""
Identity Resolution Module

This module handles the FIRST step of the Paper Finder pipeline:
resolving any input (DOI, ISBN, URL, title, citation) to a canonical metadata record.

This is separate from acquisition - we first figure out WHAT paper/book we're looking for,
then we acquire it.
"""

import re
from typing import Optional, Dict, Any, List
from pathlib import Path
import requests


class IdentityResolver:
    """
    Resolves arbitrary references to canonical metadata records.
    
    Input can be:
    - DOI (10.1038/nature12373)
    - ISBN (978-0226458083)
    - URL (https://doi.org/10.1038/nature12373, arxiv.org/abs/2311.12345)
    - arXiv ID (arXiv:2311.12345)
    - bioRxiv/medRxiv DOI (10.1101/2023.07.04.547696)
    - Title with optional authors/year
    - Messy citation text
    """
    
    def __init__(self, session: requests.Session = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def resolve(self, reference: str) -> Dict[str, Any]:
        """
        Main entry point: resolve any reference to a canonical record.
        
        Returns:
        {
            "identifier": {
                "type": "doi" | "isbn" | "arxiv" | "biorxiv" | "medrxiv" | "url" | "title",
                "value": "10.1038/171737a0"
            },
            "title": "Molecular structure of nucleic acids",
            "authors": ["J. D. Watson", "F. H. C. Crick"],
            "year": 1953,
            "journal": "Nature", 
            "publisher": "Nature Publishing Group",
            "volume": "171",
            "issue": "4356",
            "pages": "737-738",
            "abstract": "...",
            "metadata_source": "crossref" | "arxiv" | "isbn_db" | "manual"
        }
        """
        if not reference:
            return self._empty_record("No reference provided")
        
        reference = reference.strip()
        
        # 1. Check if it's an ISBN
        isbn = self._extract_isbn(reference)
        if isbn:
            return self._resolve_isbn(isbn)
        
        # 2. Check for arXiv patterns BEFORE general DOI extraction
        arxiv_id = self._extract_arxiv_id(reference)
        if arxiv_id:
            return self._resolve_arxiv(arxiv_id)
        
        # 3. Check for bioRxiv/medRxiv patterns
        biorxiv_id = self._extract_biorxiv_id(reference)
        if biorxiv_id:
            return self._resolve_biorxiv(biorxiv_id)
        
        # 4. Try to extract a DOI
        doi = self._extract_doi(reference)
        if doi:
            # Check if it's actually an arXiv DOI (10.48550/arXiv.*)
            if doi.lower().startswith("10.48550/arxiv."):
                arxiv_id = doi.lower().split("arxiv.", 1)[-1]
                return self._resolve_arxiv(arxiv_id)
            # Check if it's a bioRxiv/medRxiv DOI (10.1101/*)
            elif doi.startswith("10.1101/"):
                return self._resolve_biorxiv(doi)
            else:
                # Primary path: try to resolve DOI via Crossref (with canonical redirect)
                record = self._resolve_doi(doi)

                # If we had a network error during verification, accept the DOI optimistically
                # This prevents blocking valid papers during internet hiccups/rate-limiting
                if record.get("metadata_source") == "manual_network_error":
                    print(f"  ⚠ Network error validating DOI {doi} - proceeding optimistically")
                    return record

                # If we obtained real metadata, accept it
                if record.get("metadata_source") != "manual" and (
                    record.get("title") or record.get("journal") or record.get("authors")
                ):
                    return record

                # If the reference was just this DOI (or a minimal wrapper around it),
                # avoid guessing via free-text citation search. Treat as identity
                # failure instead of mis-resolving to an unrelated paper.
                if self._reference_is_just_this_doi(reference, doi):
                    failure = self._empty_record(error=f"DOI not found in Crossref/doi.org: {doi}")
                    failure["input_doi"] = doi
                    return failure

                # Fallback 1: treat the whole reference as a citation and ask Crossref
                # to resolve it. This can recover from slightly wrong DOIs when
                # Crossref knows the canonical record and the reference contains more
                # context than just the DOI.
                citation_record = self._resolve_citation(reference)
                id_type = citation_record.get("identifier", {}).get("type")
                if id_type == "doi" and citation_record.get("metadata_source") != "manual" and (
                    citation_record.get("title") or citation_record.get("journal")
                ):
                    # Preserve the original (possibly wrong) DOI for transparency
                    citation_record["original_input"] = reference
                    citation_record["original_doi"] = doi
                    return citation_record

                # Fallback 2: identity failure – do NOT claim this as a valid DOI.
                failure = self._empty_record(error=f"DOI not found in Crossref/doi.org: {doi}")
                failure["input_doi"] = doi
                return failure
        
        # 5. Check for direct URLs
        url_type = self._classify_url(reference)
        if url_type:
            return self._resolve_url(reference, url_type)
        
        # 6. Try title/citation resolution via Crossref (but validate first)
        # Don't search Crossref for obviously malformed inputs
        if self._is_likely_garbage(reference):
            return self._empty_record(error=f"Input appears malformed and cannot be resolved: {reference}")
        
        return self._resolve_citation(reference)
    
    def _is_likely_garbage(self, text: str) -> bool:
        """Check if input appears to be garbage that shouldn't be searched."""
        if not text:
            return True
        
        text = text.strip().lower()
        
        # Too short to be a meaningful citation
        if len(text) < 4:
            return True
        
        # Common test/garbage patterns
        garbage_patterns = [
            'not-a-doi',
            'fake-doi', 
            'test-doi',
            'invalid-doi',
            'malformed-doi',
            'nonsense',
            'garbage',
            'asdf',
            'qwerty',
            '12345',
            'xxxxx'
        ]
        
        for pattern in garbage_patterns:
            if pattern in text:
                return True
        
        # All numbers/symbols, no letters (except valid identifiers already caught)
        if re.match(r'^[0-9\-\./_]+$', text):
            return True
        
        return False
    
    def _empty_record(self, error: str = None) -> Dict[str, Any]:
        """Return an empty/error record."""
        return {
            "identifier": {"type": "unknown", "value": None},
            "error": error,
            "title": None,
            "authors": [],
            "year": None,
            "journal": None,
            "publisher": None
        }

    def _reference_is_just_this_doi(self, reference: str, doi: str) -> bool:
        """Check if the reference is essentially just this DOI.

        This helps us decide whether it's safe to treat the entire reference
        as a free-text citation for Crossref search. If the user only gave a
        bare DOI (or a simple doi.org URL / "doi:" prefix), using the whole
        string as a citation can easily mis-resolve to an unrelated paper.
        In that case we prefer to fail identity resolution instead of
        guessing.
        """
        if not reference or not doi:
            return False

        ref = reference.strip()
        doi_norm = doi.strip().lower()
        ref_lower = ref.lower().rstrip(").,;\"'`")

        # Exact match
        if ref_lower == doi_norm:
            return True

        # Simple "doi: <doi>" patterns
        if ref_lower in {f"doi:{doi_norm}", f"doi: {doi_norm}", f"doi {doi_norm}"}:
            return True

        # doi.org URL variants
        if "doi.org/" in ref_lower:
            # Strip scheme and host up to doi.org/
            parts = ref_lower.split("doi.org/", 1)
            if len(parts) == 2:
                tail = parts[1].lstrip("/").rstrip(").,;\"'`")
                if tail == doi_norm:
                    return True

        return False
    
    def _extract_isbn(self, text: str) -> Optional[str]:
        """Extract ISBN-10 or ISBN-13 from text."""
        # Remove common prefixes
        text = re.sub(r'ISBN[:\s-]*', '', text, flags=re.IGNORECASE)
        
        # Check if entire string is just ISBN-like
        clean = text.replace('-', '').replace(' ', '').replace('X', '').replace('x', '')
        if clean.isdigit() and len(clean) in [10, 13]:
            return clean
        
        # ISBN-13 pattern: 978-x-xxx-xxxxx-x
        match = re.search(r'\b(97[89][\d\-\s]{10,})\b', text)
        if match:
            isbn = re.sub(r'[\s\-]', '', match.group(1))
            if len(isbn) == 13 and isbn.isdigit():
                return isbn
        
        # ISBN-10 pattern
        match = re.search(r'\b([\d\-\s]{9,}[\dXx])\b', text)
        if match:
            isbn = re.sub(r'[\s\-]', '', match.group(1)).upper()
            if len(isbn) == 10:
                return isbn
        
        return None
    
    def _extract_arxiv_id(self, text: str) -> Optional[str]:
        """Extract arXiv ID from various formats."""
        # Pattern 1: arXiv:YYMM.NNNNN or arXiv:YYMM.NNNNNvN
        match = re.search(r'arxiv[:\s]*(\d{4}\.\d{4,5}(?:v\d+)?)', text, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # Pattern 2: arxiv.org/abs/YYMM.NNNNN
        match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', text, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # Pattern 3: Old format arXiv:subject/YYMMNNN
        match = re.search(r'arxiv[:\s]*([a-z\-]+/\d{7})', text, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return None
    
    def _extract_biorxiv_id(self, text: str) -> Optional[str]:
        """Extract bioRxiv/medRxiv DOI or ID."""
        # Pattern 1: Direct DOI
        match = re.search(r'\b(10\.1101/[\d.]+)', text)
        if match:
            return match.group(1)
        
        # Pattern 2: bioRxiv/medRxiv URL
        match = re.search(r'(?:biorxiv|medrxiv)\.org/content/(10\.1101/[\d.]+)', text, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # Pattern 3: Just the numeric part after domain
        match = re.search(r'(?:biorxiv|medrxiv)\.org/content/(?:early/\d+/\d+/\d+/)?(\d{4}\.\d{2}\.\d{2}\.\d+)', text, re.IGNORECASE)
        if match:
            # Convert to DOI format
            return f"10.1101/{match.group(1)}"
        
        return None
    
    def _extract_doi(self, text: str) -> Optional[str]:
        """Extract DOI from text."""
        # Normalize whitespace
        s = " ".join(text.strip().split())
        s = s.rstrip("`'\"")
        
        # Special case: Nature article URLs
        match = re.search(r'nature\.com/articles/([A-Za-z0-9.\-]+)', s, re.IGNORECASE)
        if match:
            return f"10.1038/{match.group(1)}"
        
        # Pattern 1: doi.org URL
        match = re.search(r'doi\.org/(10\.\d{4,}/[^\s\'"<>]+)', s, re.IGNORECASE)
        if match:
            doi = match.group(1).rstrip(").,;\"']`")
            return self._normalize_doi(doi)
        
        # Pattern 2: DOI with prefix
        match = re.search(r'doi[:\s]+(10\.\d{4,}/[^\s\'"<>]+)', s, re.IGNORECASE)
        if match:
            doi = match.group(1).rstrip(").,;\"']`")
            return self._normalize_doi(doi)
        
        # Pattern 3: Bare DOI
        match = re.search(r'\b(10\.\d{4,9}/[^\s]+)', s)
        if match:
            doi = match.group(1).rstrip(").,;\"']`")
            return self._normalize_doi(doi)
        
        return None
    
    def _normalize_doi(self, doi: str) -> str:
        """Normalize DOI by removing SI suffixes."""
        if not doi:
            return doi
        
        # If a URL accidentally got concatenated onto the DOI (e.g.
        # '10.1021/ja01080a054https://pubs.acs.org/doi/10.1021/ja01080a054'),
        # keep only the part before any new URL fragment.
        import re as _re
        parts = _re.split(r"https?://", doi, maxsplit=1)
        doi = parts[0]

        # Remove supplementary info suffixes (e.g., .s001)
        match = re.match(r'(.+)\.s\d+$', doi, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return doi
    
    def _classify_url(self, text: str) -> Optional[str]:
        """Classify a URL to determine its type."""
        if not text.startswith(('http://', 'https://')):
            return None
        
        text_lower = text.lower()
        
        if 'arxiv.org' in text_lower:
            return 'arxiv'
        elif 'biorxiv.org' in text_lower:
            return 'biorxiv'
        elif 'medrxiv.org' in text_lower:
            return 'medrxiv'
        elif 'doi.org' in text_lower:
            return 'doi'
        elif 'nature.com' in text_lower:
            return 'nature'
        elif 'science.org' in text_lower or 'sciencemag.org' in text_lower:
            return 'science'
        elif 'cell.com' in text_lower:
            return 'cell'
        elif 'plos.org' in text_lower or 'plosone.org' in text_lower:
            return 'plos'
        elif 'zenodo.org' in text_lower:
            return 'zenodo'
        elif 'figshare.com' in text_lower:
            return 'figshare'
        elif 'scielo' in text_lower:
            return 'scielo'
        
        return 'publisher'
    
    def _resolve_isbn(self, isbn: str) -> Dict[str, Any]:
        """Resolve ISBN to book metadata."""
        try:
            from src.utils.isbn_lookup import lookup_isbn
            metadata = lookup_isbn(isbn)
            
            if metadata:
                return {
                    "identifier": {"type": "isbn", "value": isbn},
                    "title": metadata.get('title'),
                    "authors": metadata.get('authors', []),
                    "year": metadata.get('year'),
                    "journal": None,  # Books don't have journals
                    "publisher": metadata.get('publisher'),
                    "isbn": isbn,
                    "metadata_source": "isbn_db",
                    "original_metadata": metadata
                }
        except ImportError:
            pass
        except Exception as e:
            print(f"ISBN lookup failed: {e}")
        
        # Return minimal record if lookup fails
        return {
            "identifier": {"type": "isbn", "value": isbn},
            "title": None,
            "authors": [],
            "year": None,
            "journal": None,
            "publisher": None,
            "isbn": isbn,
            "metadata_source": "manual"
        }
    
    def _resolve_arxiv(self, arxiv_id: str) -> Dict[str, Any]:
        """Resolve arXiv ID to metadata."""
        # Try to get metadata from arXiv API
        try:
            url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
            response = self.session.get(url, timeout=15)
            
            if response.status_code == 200:
                # Parse XML response
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                
                # Define namespace
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                
                # Find entry
                entry = root.find('atom:entry', ns)
                if entry is not None:
                    title_elem = entry.find('atom:title', ns)
                    title = title_elem.text.strip() if title_elem is not None else None
                    
                    # Authors
                    authors = []
                    for author in entry.findall('atom:author', ns):
                        name_elem = author.find('atom:name', ns)
                        if name_elem is not None:
                            authors.append(name_elem.text.strip())
                    
                    # Published date
                    published_elem = entry.find('atom:published', ns)
                    year = None
                    if published_elem is not None:
                        year_str = published_elem.text[:4]
                        try:
                            year = int(year_str)
                        except:
                            pass
                    
                    # Abstract
                    summary_elem = entry.find('atom:summary', ns)
                    abstract = summary_elem.text.strip() if summary_elem is not None else None
                    
                    return {
                        "identifier": {"type": "arxiv", "value": arxiv_id},
                        "title": title,
                        "authors": authors,
                        "year": year,
                        "journal": "arXiv",
                        "publisher": "arXiv",
                        "abstract": abstract,
                        "arxiv_id": arxiv_id,
                        "metadata_source": "arxiv",
                        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                        "html_url": f"https://arxiv.org/abs/{arxiv_id}"
                    }
        except Exception as e:
            print(f"arXiv API failed: {e}")
        
        # Return minimal record
        return {
            "identifier": {"type": "arxiv", "value": arxiv_id},
            "title": None,
            "authors": [],
            "year": None,
            "journal": "arXiv",
            "publisher": "arXiv",
            "arxiv_id": arxiv_id,
            "metadata_source": "manual",
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            "html_url": f"https://arxiv.org/abs/{arxiv_id}"
        }
    
    def _resolve_biorxiv(self, biorxiv_doi: str) -> Dict[str, Any]:
        """Resolve bioRxiv/medRxiv DOI to metadata."""
        # First try Crossref (bioRxiv/medRxiv submit to Crossref)
        record = self._resolve_doi(biorxiv_doi)
        
        # Enhance with bioRxiv-specific info
        if record and record.get("identifier", {}).get("value"):
            record["biorxiv_doi"] = biorxiv_doi
            
            # Determine which server
            server = "biorxiv"  # Default
            publisher = record.get("publisher") or ""
            if publisher.lower() == "cold spring harbor laboratory":
                # Could be either, check title/journal for hints
                journal = record.get("journal") or ""
                if "medrxiv" in str(journal).lower():
                    server = "medrxiv"
            
            # Add direct URLs
            record["pdf_url"] = f"https://www.{server}.org/content/{biorxiv_doi}.full.pdf"
            record["html_url"] = f"https://www.{server}.org/content/{biorxiv_doi}"
            
            return record
        
        # If Crossref fails, return minimal record
        return {
            "identifier": {"type": "biorxiv", "value": biorxiv_doi},
            "title": None,
            "authors": [],
            "year": None,
            "journal": "bioRxiv/medRxiv",
            "publisher": "Cold Spring Harbor Laboratory",
            "biorxiv_doi": biorxiv_doi,
            "metadata_source": "manual",
            "pdf_url": f"https://www.biorxiv.org/content/{biorxiv_doi}.full.pdf",
            "html_url": f"https://www.biorxiv.org/content/{biorxiv_doi}"
        }
    
    def _resolve_doi(self, doi: str) -> Dict[str, Any]:
        """Resolve DOI to metadata using Crossref."""
        try:
            url = f"https://api.crossref.org/works/{doi}"
            response = self.session.get(url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                message = data.get("message", {})
                
                # Extract metadata
                title = ""
                titles = message.get("title", [])
                if titles:
                    title = titles[0]
                
                # Authors
                authors = []
                for author in message.get("author", []):
                    given = author.get("given", "")
                    family = author.get("family", "")
                    if family:
                        full_name = f"{given} {family}".strip()
                        authors.append(full_name)
                
                # Year
                year = None
                date_parts = message.get("published-print", message.get("published-online", {}))
                if date_parts:
                    parts = date_parts.get("date-parts", [[]])
                    if parts and parts[0]:
                        year = parts[0][0]
                
                # Journal
                journal = ""
                containers = message.get("container-title", [])
                if containers:
                    journal = containers[0]
                
                # Publisher
                publisher = message.get("publisher", "")
                
                # Volume, issue, pages
                volume = message.get("volume")
                issue = message.get("issue")
                page = message.get("page")
                
                # Abstract
                abstract = message.get("abstract")
                
                return {
                    "identifier": {"type": "doi", "value": doi},
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "journal": journal,
                    "publisher": publisher,
                    "volume": volume,
                    "issue": issue,
                    "pages": page,
                    "abstract": abstract,
                    "doi": doi,
                    "metadata_source": "crossref",
                    "crossref_type": message.get("type"),
                    "original_metadata": message
                }
        except Exception as e:
            print(f"Crossref lookup failed: {e}")
        
        # Return minimal record
        return {
            "identifier": {"type": "doi", "value": doi},
            "title": None,
            "authors": [],
            "year": None,
            "journal": None,
            "publisher": None,
            "doi": doi,
            "metadata_source": "manual"
        }

    def _resolve_canonical_doi_via_redirect(self, doi: str) -> Optional[str]:
        '''Try to resolve a canonical DOI using https://doi.org redirects, with AAAS journal heuristics.

        This is used when Crossref /works/{doi} fails. It follows the DOI
        resolver, examines the final URL, and tries to extract a clean DOI
        from it. Additionally, for AAAS journals, it tries common prefix swaps
        (e.g., science → sciadv for Science Advances).
        '''
        try:
            resolver_url = f'https://doi.org/{doi}'
            response = self.session.get(resolver_url, timeout=15, allow_redirects=True)
            final_url = getattr(response, 'url', resolver_url) or resolver_url

            # Try to extract a DOI directly from the final URL
            canonical = self._extract_doi(final_url)
            if canonical and canonical != doi:
                return canonical
        except Exception as e:
            print(f'DOI redirect resolution failed for {doi}: {e}')

        # Universal DOI suffix heuristic: if DOI fails, try searching Crossref by suffix
        # Extract suffix after the last /
        if '/' in doi:
            suffix = doi.split('/')[-1]
            if suffix and len(suffix) > 4:  # Avoid too short suffixes
                try:
                    search_url = "https://api.crossref.org/works"
                    params = {"query": f"DOI:{suffix}", "rows": 5}  # Get up to 5 results
                    search_response = self.session.get(search_url, params=params, timeout=10)
                    if search_response.status_code == 200:
                        search_data = search_response.json()
                        items = search_data.get("message", {}).get("items", [])
                        if len(items) == 1:  # Only if exactly one match
                            found_doi = items[0].get("DOI")
                            if found_doi and found_doi != doi:
                                print(f'Trying universal DOI suffix heuristic: {doi} → {found_doi} (via suffix "{suffix}")')
                                return found_doi
                except Exception as e:
                    pass  # Heuristic failed, continue

        return None

    def _resolve_doi(self, doi: str, _depth: int = 0) -> Dict[str, Any]:
        '''Resolve DOI to metadata using Crossref, with canonical DOI fallback.

        If Crossref fails for the initial DOI, we try to resolve a canonical DOI
        via https://doi.org redirects and then retry Crossref once with that
        canonical value.
        '''
        try:
            url = f'https://api.crossref.org/works/{doi}'
            response = self.session.get(url, timeout=15)

            if response.status_code == 200:
                data = response.json()
                message = data.get('message', {})

                # Extract metadata
                title = ''
                titles = message.get('title', [])
                if titles:
                    title = titles[0]

                # Authors
                authors = []
                for author in message.get('author', []):
                    given = author.get('given', '')
                    family = author.get('family', '')
                    if family:
                        full_name = f'{given} {family}'.strip()
                        authors.append(full_name)

                # Year
                year = None
                date_parts = message.get('published-print', message.get('published-online', {}))
                if date_parts:
                    parts = date_parts.get('date-parts', [[]])
                    if parts and parts[0]:
                        year = parts[0][0]

                # Journal
                journal = ''
                containers = message.get('container-title', [])
                if containers:
                    journal = containers[0]

                # Publisher
                publisher = message.get('publisher', '')

                # Volume, issue, pages
                volume = message.get('volume')
                issue = message.get('issue')
                page = message.get('page')

                # Abstract
                abstract = message.get('abstract')

                return {
                    'identifier': {'type': 'doi', 'value': doi},
                    'title': title,
                    'authors': authors,
                    'year': year,
                    'journal': journal,
                    'publisher': publisher,
                    'volume': volume,
                    'issue': issue,
                    'pages': page,
                    'abstract': abstract,
                    'doi': doi,
                    'metadata_source': 'crossref',
                    'crossref_type': message.get('type'),
                    'original_metadata': message,
                }
            else:
                print(f'Crossref lookup for DOI {doi} returned status {response.status_code}')
        except (requests.exceptions.RequestException, ConnectionError, OSError) as e:
            print(f'Crossref lookup failed (Network Error: {type(e).__name__}) for DOI {doi}: {e}')
            # Return minimal record but mark as network error so we don't abort resolution
            return {
                'identifier': {'type': 'doi', 'value': doi},
                'title': None,
                'authors': [],
                'year': None,
                'journal': None,
                'publisher': None,
                'doi': doi,
                'metadata_source': 'manual_network_error',
            }
        except Exception as e:
            print(f'Crossref lookup failed for DOI {doi}: {e}')

        # If Crossref failed and we haven't yet tried canonical resolution, do that now
        if _depth == 0:
            canonical = self._resolve_canonical_doi_via_redirect(doi)
            if canonical and canonical != doi:
                print(f'Resolved canonical DOI via redirect: {canonical} (from {doi})')
                return self._resolve_doi(canonical, _depth=1)

        # Return minimal record if everything fails
        return {
            'identifier': {'type': 'doi', 'value': doi},
            'title': None,
            'authors': [],
            'year': None,
            'journal': None,
            'publisher': None,
            'doi': doi,
            'metadata_source': 'manual',
        }

    def _resolve_url(self, url: str, url_type: str) -> Dict[str, Any]:
        """Resolve based on URL type."""
        if url_type == 'arxiv':
            arxiv_id = self._extract_arxiv_id(url)
            if arxiv_id:
                return self._resolve_arxiv(arxiv_id)
        elif url_type in ['biorxiv', 'medrxiv']:
            biorxiv_id = self._extract_biorxiv_id(url)
            if biorxiv_id:
                return self._resolve_biorxiv(biorxiv_id)
        elif url_type == 'doi':
            doi = self._extract_doi(url)
            if doi:
                return self._resolve_doi(doi)
        
        # For other URLs, try to extract identifiers
        doi = self._extract_doi(url)
        if doi:
            return self._resolve_doi(doi)
        
        # Return URL-based record
        return {
            "identifier": {"type": "url", "value": url},
            "title": None,
            "authors": [],
            "year": None,
            "journal": None,
            "publisher": None,
            "url": url,
            "url_type": url_type,
            "metadata_source": "manual"
        }
    
    def _resolve_citation(self, citation: str) -> Dict[str, Any]:
        """Try to resolve a free-text citation via Crossref search."""
        try:
            # Clean up citation for better matching
            citation = self._normalize_citation(citation)
            
            url = "https://api.crossref.org/works"
            params = {
                "query": citation[:500],  # Limit length
                "rows": 1
            }
            response = self.session.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("message", {}).get("items", [])
                if items:
                    doi = items[0].get("DOI")
                    if doi:
                        print(f"Resolved citation via Crossref to DOI: {doi}")
                        return self._resolve_doi(doi)
        except Exception as e:
            print(f"Citation resolution failed: {e}")
        
        # Return title-based record
        return {
            "identifier": {"type": "title", "value": citation[:200]},
            "title": citation,
            "authors": [],
            "year": None,
            "journal": None,
            "publisher": None,
            "metadata_source": "manual",
            "original_citation": citation
        }
    
    def _normalize_citation(self, citation: str) -> str:
        """Normalize citation for better Crossref matching."""
        # Split camelCase in obviously concatenated titles
        tokens = citation.split()
        new_tokens = []
        for tok in tokens:
            # Only split very long tokens with camelCase
            if len(tok) > 25 and re.search(r'[a-z][A-Z]', tok):
                # Insert space before capitals following lowercase
                split_tok = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', tok)
                new_tokens.append(split_tok)
            else:
                new_tokens.append(tok)
        
        return ' '.join(new_tokens)
