#!/usr/bin/env python3
"""
Metadata extraction and resolution.

Handles:
- DOI extraction from references
- Reference string parsing
- Crossref metadata lookup
- Semantic Scholar integration
- ISBN detection and lookup
"""

import re
import requests
from typing import Optional, Dict, List
from pathlib import Path


class MetadataResolver:
    """Resolve references to DOIs and fetch metadata."""
    
    def __init__(self, session: requests.Session = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def extract_doi_from_text(self, text: str) -> Optional[str]:
        """
        Extract DOI from arbitrary reference string.
        
        Handles patterns like:
        - "DOI: 10.1021/jacs.3c00908"
        - "https://doi.org/10.1021/jacs.3c00908"
        - "... 10.1021/jacs.3c00908)"
        """
        from .discovery import _doi
        return _doi(text)

    def extract_isbn_from_text(self, text: str) -> Optional[str]:
        """
        Extract ISBN-10 or ISBN-13 from text.
        
        Returns normalized ISBN (digits only).
        """
        if not text:
            return None
        
        # Remove common prefixes
        text = re.sub(r'ISBN[:\s-]*', '', text, flags=re.IGNORECASE)
        
        # ISBN-13 pattern: 978-x-xxx-xxxxx-x (with or without hyphens)
        match = re.search(r'\b(97[89][\d\-\s]{10,})\b', text)
        if match:
            isbn = re.sub(r'[\s\-]', '', match.group(1))
            if len(isbn) == 13 and isbn.isdigit():
                return isbn
        
        # ISBN-10 pattern: x-xxx-xxxxx-x (with or without hyphens)
        match = re.search(r'\b([\d\-\s]{9,}[\dXx])\b', text)
        if match:
            isbn = re.sub(r'[\s\-]', '', match.group(1))
            if len(isbn) == 10:
                return isbn
        
        return None
    
    def get_crossref_metadata(self, doi: str) -> Optional[Dict]:
        """
        Get metadata from Crossref API.
        
        Returns:
            Dict with keys: title, authors, year, journal, publisher
        """
        from .discovery import _doi
        from urllib.parse import quote
        doi = _doi(doi)
        if not doi:
            return None
        try:
            url = f"https://api.crossref.org/works/{quote(doi, safe='/')}"
            response = self.session.get(url, timeout=15)
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            message = data.get("message", {})
            if not isinstance(message, dict):
                return None
            # A wrong or malformed explicit identifier contradicts this endpoint.
            # When omitted, the exact DOI endpoint itself supplies the identity.
            if "DOI" in message and _doi(message["DOI"]) != doi:
                return None

            # Extract key fields
            metadata = {
                "doi": doi,
                "title": "",
                "authors": [],
                "year": None,
                "journal": "",
                "publisher": "",
                "type": message.get("type", ""),
            }
            
            # Title
            titles = message.get("title", [])
            if titles:
                metadata["title"] = titles[0]
            
            # Authors
            authors = message.get("author", [])
            for author in authors:
                given = author.get("given", "")
                family = author.get("family", "")
                if family:
                    full_name = f"{given} {family}".strip()
                    metadata["authors"].append(full_name)
            
            # Year
            date_parts = message.get("published-print", message.get("published-online", {}))
            if date_parts:
                parts = date_parts.get("date-parts", [[]])
                if parts and parts[0]:
                    metadata["year"] = parts[0][0]
            
            # Journal/container
            containers = message.get("container-title", [])
            if containers:
                metadata["journal"] = containers[0]
                metadata["container-title"] = containers[0]
            
            # Publisher
            metadata["publisher"] = message.get("publisher", "")
            
            # ISBN (for books)
            isbns = message.get("ISBN", [])
            if isbns:
                metadata["ISBN"] = isbns[0]
            
            return metadata
            
        except Exception as e:
            print(f"  Crossref metadata failed: {type(e).__name__}")
            return None
    
    def resolve_reference(self, ref_str: str) -> Optional[str]:
        """Return a DOI only when the shared discovery service establishes a match."""
        from .discovery import DiscoveryService
        result = DiscoveryService(session=self.session).search(ref_str, mode="identify")
        selected = result.get("selected")
        return selected.get("doi") if result["status"] == "matched" and selected else None
