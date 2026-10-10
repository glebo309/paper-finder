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
    
    def __init__(self, session: requests.Session = None, refresh=False):
        self.refresh = refresh
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
                return self._resolve_doi(doi)

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
        # Both modern numeric and legacy subject identifiers may specify a
        # version. Preserve it through metadata lookup and PDF acquisition.
        identifier = r'((?:\d{4}\.\d{4,5}|[a-z][a-z.\-]*/\d{7})(?:v\d+)?)(?!\w)'
        match = re.fullmatch(identifier, text.strip(), re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'arxiv[:\s]*' + identifier, text, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'arxiv\.org/(?:abs|pdf)/' + identifier, text, re.IGNORECASE)
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
        from .discovery import _doi
        match = re.search(r'nature\.com/articles/([A-Za-z0-9.\-]+)', text, re.I)
        if match:
            return f"10.1038/{match.group(1)}"
        return _doi(text)

    def _normalize_doi(self, doi: str) -> str:
        """Normalize punctuation without converting a supplement into another work."""
        from .discovery import _doi
        return _doi(doi) or doi

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
                    entry_id = entry.findtext('atom:id', default='', namespaces=ns)
                    returned_id = self._extract_arxiv_id(entry_id)
                    requested = arxiv_id.lower()
                    returned = (returned_id or '').lower()
                    explicit_version = bool(re.search(r'v\d+$', requested))
                    same_identity = (returned == requested if explicit_version else
                                     re.sub(r'v\d+$', '', returned) == requested)
                    if not same_identity:
                        # Retain the user's exact identifier and PDF URL, but
                        # never attach another paper/version's metadata to it.
                        entry = None
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
    
    def _resolve_doi(self, doi: str, _depth: int = 0) -> Dict[str, Any]:
        """Verify the exact DOI across indexes without guessing a replacement."""
        from .discovery import DiscoveryService
        result = DiscoveryService(session=self.session, refresh=self.refresh).search(doi, mode="identify")
        if result.get("selected") is not None and result['status'] == 'matched':
            return result['selected']
        error = "Metadata providers unavailable" if result['status'] == 'unavailable' else "DOI could not be verified"
        record = self._empty_record(error=error)
        record.update(status=result['status'], input_doi=doi, candidates=result.get('candidates', []),
                      provider_errors=result.get('errors', {}))
        return record

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
        
        # Fetch only bounded HTML citation metadata. Page titles and OpenGraph
        # headings frequently describe login/error pages and are not identities.
        from html.parser import HTMLParser
        from urllib.parse import urljoin, urlsplit
        import time

        def safe_url(value):
            try:
                parsed = urlsplit(value)
                return bool(parsed.scheme in {'http', 'https'} and parsed.hostname
                            and not parsed.username and not parsed.password)
            except (TypeError, ValueError):
                return False

        def unresolved(message, status='not_found'):
            record = self._empty_record(error=message)
            record.update(status=status, input_url=url, url=url, pdf_urls=[])
            return record

        if not safe_url(url):
            return unresolved('URL must use HTTP or HTTPS without embedded credentials')

        class CitationParser(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.values = {}

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                name = (attrs.get('name') or attrs.get('property') or '').lower()
                content = (attrs.get('content') or '').strip()
                if tag.lower() == 'meta' and name.startswith('citation_') and content:
                    self.values.setdefault(name, []).append(content)

        current = url
        deadline = time.monotonic() + 15
        maximum = 1024 * 1024
        response = None
        try:
            for _ in range(4):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return unresolved('Publisher metadata request timed out', 'unavailable')
                response = self.session.get(current, stream=True, allow_redirects=False,
                                            timeout=min(5, remaining))
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location')
                    following = urljoin(current, location) if location else ''
                    response.close()
                    response = None
                    if not safe_url(following):
                        return unresolved('Publisher redirected to an unsupported URL')
                    current = following
                    continue
                if response.status_code != 200:
                    status = 'unavailable' if response.status_code in (401, 403, 429) or response.status_code >= 500 else 'not_found'
                    return unresolved(f'Publisher returned HTTP {response.status_code}', status)
                content_type = response.headers.get('Content-Type', '').lower()
                if 'html' not in content_type:
                    return unresolved('URL does not provide HTML citation metadata; direct PDF identity is unverified')
                length = response.headers.get('Content-Length')
                if length and int(length) > maximum:
                    return unresolved('Publisher HTML exceeds the metadata size limit')
                body = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    if time.monotonic() >= deadline:
                        return unresolved('Publisher metadata request timed out', 'unavailable')
                    body.extend(chunk)
                    if len(body) > maximum:
                        return unresolved('Publisher HTML exceeds the metadata size limit')
                parser = CitationParser()
                charset = re.search(r'charset=([a-zA-Z0-9_-]+)', content_type)
                encoding = charset.group(1) if charset else 'utf-8'
                try:
                    parser.feed(body.decode(encoding, errors='replace'))
                except LookupError:
                    parser.feed(body.decode('utf-8', errors='replace'))
                values = parser.values
                title = next(iter(values.get('citation_title', [])), '')
                dois = {self._extract_doi(value) for value in values.get('citation_doi', [])}
                if None in dois:
                    return unresolved('Publisher metadata contains a malformed article DOI')
                if len(dois) > 1:
                    return unresolved('Publisher metadata contains conflicting article DOIs', 'ambiguous')
                pdfs = []
                for value in values.get('citation_pdf_url', []):
                    candidate = urljoin(current, value)
                    if safe_url(candidate) and candidate not in pdfs:
                        pdfs.append(candidate)
                if dois:
                    record = self._resolve_doi(next(iter(dois)))
                    record['input_url'] = url
                    if record.get('error') or record.get('status') in {'unavailable', 'not_found', 'ambiguous'}:
                        return record
                    record['pdf_urls'] = list(dict.fromkeys(list(record.get('pdf_urls') or []) + pdfs))
                    record['sources'] = list(dict.fromkeys(list(record.get('sources') or []) + ['publisher_metadata']))
                    return record
                if not title:
                    return unresolved('No article citation title or DOI found in publisher metadata')
                date = next(iter(values.get('citation_publication_date', values.get('citation_date', []))), '')
                year_match = re.search(r'\b(?:18|19|20)\d{2}\b', date)
                return {
                    'identifier': {'type': 'url', 'value': current}, 'title': title,
                    'authors': list(dict.fromkeys(values.get('citation_author', []))),
                    'year': int(year_match.group()) if year_match else None,
                    'journal': next(iter(values.get('citation_journal_title', [])), ''),
                    'publisher': next(iter(values.get('citation_publisher', [])), ''),
                    'url': current, 'input_url': url, 'url_type': url_type,
                    'pdf_urls': pdfs, 'metadata_source': 'publisher_metadata',
                    'sources': ['publisher_metadata'], 'status': 'matched',
                    'match_reasons': ['Article citation metadata supplied by the requested publisher page'],
                }
            return unresolved('Publisher redirect limit exceeded', 'unavailable')
        except requests.RequestException:
            return unresolved('Publisher metadata could not be reached', 'unavailable')
        except (ValueError, TypeError):
            return unresolved('Publisher returned malformed metadata')
        finally:
            if response is not None:
                response.close()

    def _resolve_citation(self, citation: str) -> Dict[str, Any]:
        """Resolve text through ranked candidates; preserve ambiguity for every interface."""
        from .discovery import DiscoveryService
        result = DiscoveryService(session=self.session, refresh=self.refresh).search(citation, mode="identify")
        if result.get("selected") is not None and result["status"] == "matched":
            return result["selected"]
        record = self._empty_record(error={
            "ambiguous": "Several possible papers found. Select a candidate before downloading.",
            "unavailable": "Search providers could not be reached. Try again later.",
            "not_found": "No sufficiently matching paper found.",
        }.get(result["status"], "Paper identity could not be established"))
        record.update(status=result["status"], candidates=result.get("candidates", []),
                      provider_errors=result.get("errors", {}), original_citation=citation)
        return record

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
