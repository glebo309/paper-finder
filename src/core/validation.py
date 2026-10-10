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
    """Require a parseable PDF with at least one page; magic bytes are insufficient."""
    if not validate_pdf(path, min_size_kb=0):
        return False
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(path))
        return len(reader.pages) > 0
    except Exception:
        return False


def _normalize_text(text: str) -> str:
    """Normalize Unicode, punctuation and whitespace without losing word boundaries."""
    import re
    import unicodedata
    import html
    # Citation titles may contain inline superscript/subscript markup. Removing
    # just formatting tags preserves meaningful literal angle brackets elsewhere.
    text = re.sub(r"</?(?:sup|sub|i|b|em|strong|span)(?:\s[^>]*)?>", "", str(text), flags=re.I)
    text = unicodedata.normalize("NFKD", html.unescape(text)).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    return " ".join(re.findall(r"[^\W_]+", text, re.UNICODE))


def _title_similarity(a: str, b: str) -> float:
    """Best contiguous title window; abstracts cannot dilute an actual title."""
    from difflib import SequenceMatcher
    target, words = _normalize_text(a).split(), _normalize_text(b).split()
    if not target or not words:
        return 0.0
    width = len(target)
    if width > len(words):
        return SequenceMatcher(None, target, words).ratio()
    return max(SequenceMatcher(None, target, words[i:i + width]).ratio()
               for i in range(len(words) - width + 1))


def _dois(text: str) -> set:
    import re
    values = set()
    for value in re.findall(r"10\.\d{4,9}/[^\s\"]+", str(text), re.IGNORECASE):
        value = value.casefold().rstrip(".,;:")
        # Parentheses can belong to a DOI. Remove only unmatched wrapping
        # punctuation, preserving distinct identifiers such as example(a).
        while value and value[-1] in ")]}>":
            closing = value[-1]
            opening = {")": "(", "]": "[", "}": "{", ">": "<"}[closing]
            if value.count(closing) <= value.count(opening):
                break
            value = value[:-1].rstrip(".,;:")
        values.add(value)
    return values


def _front_matter(text: str) -> str:
    """Only material preceding body sections, never reference entries."""
    import re
    # Numeric sections, headings with a same-line abstract, and all-caps variants.
    boundary = re.search(
        r"(?im)^\s*(?:(?:[1-9][0-9]*|[IVX]+)[.\s]+)?"
        r"(?:abstract|introduction|references|bibliography|literature cited)\b", text)
    return text[:boundary.start() if boundary else 1800][:1800]


def verify_document_identity(path: Path, record: Dict) -> Dict:
    """Compare a PDF's front matter against a selected bibliographic record.

    Returns verified, mismatch, or unverifiable with explicit evidence. This is a
    conservative local heuristic, not OCR or a guarantee of document authenticity.
    A DOI quoted in the body or references is never sufficient evidence.
    """
    import re

    def result(status, reason, **evidence):
        return {"status": status, "reasons": [reason], **evidence}

    path = Path(path)
    identifier = record.get("identifier") or {}
    title = record.get("title") or record.get("Title") or ""
    if isinstance(title, list):
        title = title[0] if title else ""
    doi = record.get("doi") or (identifier.get("value") if identifier.get("type") == "doi" else "")
    wanted_dois = _dois(doi or "")
    arxiv = record.get("arxiv_id") or (identifier.get("value") if identifier.get("type") == "arxiv" else "")
    if not arxiv and doi and "10.48550/arxiv." in doi.lower():
        arxiv = doi.lower().split("10.48550/arxiv.", 1)[1]
    arxiv = str(arxiv).lower()
    arxiv_base = re.sub(r"v\d+$", "", arxiv)
    requested_version = bool(re.search(r"v\d+$", arxiv))
    if not (title or wanted_dois or arxiv):
        return result("unverifiable", "No target title or supported identifier was provided")
    try:
        if not validate_pdf(path, min_size_kb=0):
            return result("unverifiable", "File is missing or does not have a PDF header")
        from PyPDF2 import PdfReader
        reader = PdfReader(str(path))
        if not reader.pages:
            return result("unverifiable", "PDF has no pages")
        page_text = reader.pages[0].extract_text() or ""
        pdf_meta = reader.metadata or {}
    except Exception as exc:
        return result("unverifiable", f"PDF text extraction failed: {type(exc).__name__}")

    front = _front_matter(page_text)
    norm_front = _normalize_text(front)
    # Exclude arbitrary subject/keywords: these often contain cited identifiers.
    meta_dois = _dois(" ".join(str(pdf_meta.get(key) or "") for key in ("/doi", "/DOI", "/WPS-ARTICLEDOI")))
    front_dois = _dois(front)
    found_dois = front_dois | meta_dois
    expected_supplement = bool(re.search(r"supplement(?:ary|al)?|supporting information", title, re.I))
    is_supplement = bool(re.search(
        r"(?im)^\s*(?:electronic\s+)?(?:supplement(?:ary|al)?(?:\s*(?:information|materials?|data|appendix|methods))?|supporting\s*information)\s*(?:$|[:.]|for\b)",
        front))
    if is_supplement and not expected_supplement:
        return result("mismatch", "Document is supplementary material, not the selected main article")

    score = _title_similarity(title, front) if title else 0.0
    authors = record.get("authors") or record.get("author") or []
    if isinstance(authors, str):
        authors = [authors]
    names = []
    compact_matched_authors = []
    for author in authors:
        if isinstance(author, dict):
            author = author.get("family") or author.get("name") or ""
        tokens = _normalize_text(author).split()
        if tokens:
            names.append(tokens[-1])
            # Some PDF text layers omit every inter-word space. Require the
            # complete given + family name as an extracted token, not a surname
            # substring or an initial that could match unrelated text.
            compact_author = "".join(tokens)
            if (len(tokens) >= 2 and len(tokens[0]) >= 2 and len(compact_author) >= 8
                    and re.search(r"(?:^|\s)" + re.escape(compact_author) + r"\d*(?:$|\s)", norm_front)):
                compact_matched_authors.append(tokens[-1])
    matched_authors = [name for name in names if name in norm_front.split()]
    title_words = _normalize_text(title).split()
    compact_title = "".join(title_words)
    compact_heading = "".join(_normalize_text(front[:700]).split())
    compact_title_match = bool(len(title_words) >= 4 and len(compact_title) >= 24
                               and compact_title in compact_heading)
    doi_match = bool(wanted_dois & found_dois)
    compact_corroborated = compact_title_match and bool(doi_match or compact_matched_authors)
    if compact_corroborated:
        matched_authors = list(dict.fromkeys(matched_authors + compact_matched_authors))
    strong_title = (bool(title_words) and score >= .92 and (len(title_words) >= 4 or bool(matched_authors))) or compact_corroborated
    plausible_title = score >= .78 and bool(matched_authors)
    arxiv_pattern = r"arxiv\s*:\s*((?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?)"
    arxiv_values = {item.lower() for item in re.findall(arxiv_pattern, front, re.I)}
    # arXiv's margin stamp often extracts after the abstract and body. Its
    # category/date format distinguishes that stamp from ordinary body citations.
    stamps = re.findall(arxiv_pattern + r"\s*\[[a-z][a-z0-9.-]*\]\s*\d{1,2}\s+[a-z]{3}\s+\d{4}\b",
                        page_text, re.I)
    arxiv_values.update(item.lower() for item in stamps)
    arxiv_bases = {re.sub(r"v\d+$", "", item) for item in arxiv_values}
    arxiv_match = bool(arxiv and (arxiv in arxiv_values if requested_version else arxiv_base in arxiv_bases))
    evidence = {"title_similarity": round(score, 3), "compact_title_match": compact_title_match,
                "matched_authors": matched_authors,
                "front_matter_dois": sorted(found_dois), "identifier_match": doi_match or arxiv_match,
                "front_matter_arxiv_ids": sorted(arxiv_values),
                "text_extracted": bool(norm_front)}

    if arxiv and arxiv_values and arxiv_base not in arxiv_bases:
        return result("mismatch", "Front-matter arXiv identifier conflicts with the selected record", **evidence)
    if requested_version and not arxiv_match:
        explicit_versions = {item for item in arxiv_values if re.search(r"v\d+$", item)}
        if explicit_versions:
            return result("mismatch", "Front-matter arXiv version differs from the selected version", **evidence)
        return result("unverifiable", "The explicitly requested arXiv version is not corroborated", **evidence)

    # An article identifier embedded in metadata cannot erase a contradictory
    # DOI printed on the page. Identified arXiv versions can legitimately carry
    # a later journal DOI, as handled by the separate arXiv identity evidence.
    if wanted_dois and front_dois and not (wanted_dois & front_dois) and not arxiv_match:
        return result("mismatch", "Printed front-matter DOI conflicts with the selected record", **evidence)

    policy = record.get("verification_policy") or {}
    if policy.get("require_identifier") and not (doi_match or arxiv_match):
        return result("unverifiable", "Known version alternatives require the selected identifier in PDF metadata or front matter", **evidence)

    if strong_title or plausible_title:
        if names and not matched_authors and not (doi_match or arxiv_match):
            return result("unverifiable", "Title matches but none of the expected authors are corroborated", **evidence)
        # A conflicting explicit article DOI is a real contradiction, unless this
        # is an identified arXiv version carrying a later journal DOI.
        if wanted_dois and found_dois and not doi_match and not arxiv_match:
            return result("mismatch", "Front-matter DOI conflicts with the selected record", **evidence)
        return result("verified", "Title matches the first-page heading" +
                      (" after word-spacing normalization" if compact_corroborated and score < .92 else "") +
                      (" with author corroboration" if matched_authors else ""), **evidence)
    if doi_match or arxiv_match:
        if title and len(norm_front.split()) >= 5 and score < .35:
            return result("unverifiable", "Identifier matches but the expected title is not corroborated", **evidence)
        return result("verified", "Exact identifier matches PDF metadata or front matter", **evidence)
    if not norm_front:
        return result("unverifiable", "PDF has no extractable first-page text or matching identifier metadata", **evidence)
    if wanted_dois and found_dois and not (wanted_dois & found_dois):
        return result("mismatch", "Front-matter DOI differs from the selected record", **evidence)
    if title and len(norm_front.split()) >= 4 and score < .35:
        return result("mismatch", "First-page heading does not match the selected paper", **evidence)
    return result("unverifiable", "Insufficient front-matter evidence to confirm the selected paper", **evidence)


def validate_pdf_contains_doi(path: Path, expected_doi: str, max_pages: int = 5) -> Optional[bool]:
    """Legacy tri-state API; identifiers must occur in front matter, not citations.

    max_pages remains accepted for compatibility; identity uses the first page.
    """
    result = verify_document_identity(path, {"doi": expected_doi})
    if result["status"] == "unverifiable":
        return False if result.get("text_extracted") else None
    return result["status"] == "verified"


def validate_pdf_matches_metadata(path: Path, metadata: Dict, doi: Optional[str],
                                  source_name: str, max_pages: int = 5) -> bool:
    """Legacy bool API: only affirmative evidence succeeds, regardless of source."""
    record = dict(metadata)
    if doi:
        record["doi"] = doi
    return verify_document_identity(path, record)["status"] == "verified"
