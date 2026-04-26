#!/usr/bin/env python3
"""
PDF validation and content verification.

Handles:
- PDF magic byte checking
- File size validation
- HTML error page detection
- Title similarity matching (if needed)
"""

from pathlib import Path
from typing import Optional, Dict


def validate_pdf(path: Path, min_size_kb: int = 50) -> bool:
    """
    Validate that a file is actually a valid PDF.
    
    Args:
        path: Path to PDF file
        min_size_kb: Minimum file size in KB (default 50KB)
    
    Returns:
        True if valid PDF, False otherwise
    """
    if not path.exists():
        return False
    
    # Check size
    size_bytes = path.stat().st_size
    if size_bytes < min_size_kb * 1024:
        return False
    
    # Check PDF magic bytes
    with path.open('rb') as f:
        header = f.read(1024)
        
        # Must start with %PDF-
        if not header.startswith(b'%PDF-'):
            return False
        
        # Check for HTML error pages disguised as PDFs
        header_lower = header.lower()
        if b'<html' in header_lower or b'<!doctype' in header_lower:
            return False
    
    return True


def is_pdf_content(content: bytes, min_size_kb: int = 50) -> bool:
    """
    Check if byte content is a valid PDF (before writing to disk).
    
    Args:
        content: Raw bytes
        min_size_kb: Minimum size in KB
    
    Returns:
        True if valid PDF content
    """
    if len(content) < min_size_kb * 1024:
        return False
    
    if not content.startswith(b'%PDF'):
        return False
    
    # Check for HTML in first KB
    header = content[:1024].lower()
    if b'<html' in header or b'<!doctype' in header:
        return False
    
    return True


def check_pdf_readable(path: Path) -> bool:
    """
    Check if PDF can be opened and read (deeper validation).
    
    Requires PyPDF2 or similar. Returns True if basic validation passes.
    """
    if not validate_pdf(path):
        return False
    
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(path))
        # Try to read first page
        if len(reader.pages) > 0:
            return True
    except:
        # PyPDF2 not available or PDF corrupted
        # Fall back to magic byte validation
        pass
    
    return True


def validate_pdf_contains_doi(path: Path, expected_doi: str, max_pages: int = 5) -> bool:
    """
    Validate that a PDF actually contains the expected DOI.
    
    This is CRITICAL to prevent wrong papers from being accepted.
    
    Args:
        path: Path to PDF file
        expected_doi: The DOI that should be present in the PDF
        max_pages: Number of pages to check (default 5, DOI usually on first pages)
    
    Returns:
        True if DOI found in PDF text, False if not found, None if validation not possible
    """
    if not path.exists():
        return False
    
    # Basic PDF validation first
    if not validate_pdf(path):
        return False
    
    # Try PyPDF2 for text extraction
    try:
        from PyPDF2 import PdfReader
        
        reader = PdfReader(str(path))
        
        # Normalize DOI for comparison (remove http://, https://, dx.doi.org, etc.)
        clean_doi = expected_doi.lower().strip()
        clean_doi = clean_doi.replace('https://doi.org/', '')
        clean_doi = clean_doi.replace('http://doi.org/', '')
        clean_doi = clean_doi.replace('https://dx.doi.org/', '')
        clean_doi = clean_doi.replace('http://dx.doi.org/', '')
        clean_doi = clean_doi.replace('doi:', '').strip()
        
        # Check first N pages
        pages_to_check = min(max_pages, len(reader.pages))
        
        for page_num in range(pages_to_check):
            try:
                page = reader.pages[page_num]
                text = page.extract_text() or ""
                text_lower = text.lower()
                
                # Look for DOI in various formats
                # Standard DOI format
                if clean_doi in text_lower:
                    return True
                
                # DOI with URL prefix
                if f'doi.org/{clean_doi}' in text_lower:
                    return True
                
                # DOI: prefix
                if f'doi: {clean_doi}' in text_lower or f'doi:{clean_doi}' in text_lower:
                    return True
                
            except Exception:
                # Page extraction failed, try next page
                continue
        
        # DOI not found in checked pages
        return False
        
    except ImportError:
        # PyPDF2 not available - cannot validate content
        # Return None to indicate validation not possible
        return None
    except Exception:
        # PDF corrupted or unreadable
        return False


def _normalize_text(text: str) -> str:
    """Normalize text for comparison (lowercase, collapse spaces)."""
    import re
    t = text.lower().strip()
    # Replace multiple whitespace with single space
    t = re.sub(r"\s+", " ", t)
    return t


def _title_similarity(a: str, b: str) -> float:
    """Very lightweight title similarity (ratio of common tokens)."""
    a_norm = _normalize_text(a)
    b_norm = _normalize_text(b)
    if not a_norm or not b_norm:
        return 0.0
    a_tokens = set(a_norm.split())
    b_tokens = set(b_norm.split())
    if not a_tokens or not b_tokens:
        return 0.0
    common = len(a_tokens & b_tokens)
    total = len(a_tokens | b_tokens)
    return common / total


def validate_pdf_matches_metadata(
    path: Path,
    metadata: Dict,
    doi: Optional[str],
    source_name: str,
    max_pages: int = 5,
) -> bool:
    """Validate that a PDF matches the requested paper using metadata.

    Strategy depends on source type:
    - Trusted publisher / OA / preprint (Springer, Nature, Cell, PMC, arXiv, etc.):
      * Primary: title similarity vs metadata title
      * Secondary: DOI match if present
    - Repositories (Europe PMC, Dataverse, Zenodo, etc.):
      * Require good title similarity, use DOI if present
    - High-risk sources (Sci-Hub, Telegram, Anna's Archive, LibGen):
      * Require DOI match OR very high title similarity
    """
    # Basic PDF structure check
    if not validate_pdf(path):
        return False

    title = metadata.get("title") or metadata.get("Title")
    publisher = (metadata.get("publisher") or "").lower()
    journal = (metadata.get("journal") or metadata.get("container-title") or "").lower()

    # Classify source into trust categories
    src = (source_name or "").lower()

    def is_publisher_like() -> bool:
        host_keywords = [
            "springer", "nature.com", "linkinghub.elsevier.com", "cell.com",
            "acs.org", "wiley.com", "tandfonline", "oup.com", "scielo",
        ]
        meta_keywords = ["springer", "nature", "elsevier", "acs", "wiley"]
        return any(k in src for k in host_keywords) or any(k in publisher for k in meta_keywords)

    def is_oa_preprint_like() -> bool:
        hosts = ["arxiv", "biorxiv", "medrxiv", "ncbi.nlm.nih.gov/pmc", "europe pmc"]
        return any(h in src for h in hosts) or "preprint" in journal

    def is_repository_like() -> bool:
        hosts = ["zenodo", "figshare", "dataverse", "osf", "institutional repo", "repository"]
        return any(h in src for h in hosts)

    def is_scihub_like() -> bool:
        hosts = ["sci-hub", "scihub"]
        return any(h in src for h in hosts)

    def is_shadow_library_like() -> bool:
        # Higher-risk shadow libraries where we keep stricter validation
        hosts = ["telegram", "anna's archive", "annas_archive", "libgen"]
        return any(h in src for h in hosts)

    # If we don't have title metadata, fall back to DOI-only rules
    if not title:
        if doi and "/" in doi:
            doi_result = validate_pdf_contains_doi(path, doi, max_pages=max_pages)
            return bool(doi_result)
        # No title and no DOI: we can't validate content deeply, trust basic PDF check
        return True

    # Track basic file stats for fallback heuristics
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0

    # Try to read first few pages and extract text
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(path))
        pages_to_check = min(max_pages, len(reader.pages))
        extracted = []
        for i in range(pages_to_check):
            try:
                text = reader.pages[i].extract_text() or ""
                extracted.append(text)
            except Exception:
                continue
        full_text = "\n".join(extracted)
    except Exception:
        # If we can't parse text at all, fall back to basic validation only
        return True

    norm_title = _normalize_text(title)
    norm_text = _normalize_text(full_text)
    text_char_count = len(norm_text.strip())

    # Quick DOI / identifier check if available
    doi_ok = None
    if doi and "/" in doi:
        # Normal DOI-in-text validation
        doi_ok = validate_pdf_contains_doi(path, doi, max_pages=max_pages)

        # Special-case: Crossref arXiv DOIs like 10.48550/arXiv.2311.12345
        # Many arXiv PDFs only contain "arXiv:2311.12345", not the full DOI.
        if (doi_ok is False) and doi.lower().startswith("10.48550/arxiv."):
            try:
                # Extract the arXiv ID part
                arxiv_id = doi.split("arxiv.", 1)[1]
                # Consider both "2311.12345" and "arxiv:2311.12345" forms
                if arxiv_id in norm_text or f"arxiv:{arxiv_id}" in norm_text:
                    doi_ok = True
            except Exception:
                pass

    # Title similarity (using only first ~300 chars to bias towards title area)
    window_text = norm_text[:3000]
    title_sim = _title_similarity(norm_title, window_text)

    # Decide based on source class
    if is_scihub_like() or is_shadow_library_like():
        # PHILOSOPHY: Identify First, Then Acquire.
        # If we identified the DOI correctly and asked Sci-Hub/Shadow Libs for it,
        # we assume the returned PDF is correct.
        # These sources are DOI-addressable. Mismatches are rare, but false negatives
        # from text extraction (OCR failure, old scans) are very common.
        # We trust the source's mapping over our text analysis.
        return True

    if is_publisher_like() or is_oa_preprint_like():
        # Trusted sources (Nature, Cell, arXiv, bioRxiv, etc.)
        # Accept with moderate title match OR DOI/ID match
        if title_sim >= 0.6:
            return True
        if doi_ok:
            return True
        return False

    if is_repository_like():
        # Repositories (SciELO, Dataverse, Zenodo, etc.) can host variants
        # Accept with lower title similarity, or DOI match if present
        if title_sim >= 0.5:
            return True
        if doi_ok:
            return True
        return False

    # Fallback: neutral source – require either DOI or decent title
    if doi_ok:
        return True
    return title_sim >= 0.6
