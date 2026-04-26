#!/usr/bin/env python3
"""
Quick validation script to check if downloaded PDFs contain the expected DOIs.
Run this to verify that downloaded papers are actually correct.
"""

from pathlib import Path
from typing import Dict, Optional

try:
    from PyPDF2 import PdfReader
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    print("⚠️  PyPDF2 not available. Install with: pip install PyPDF2")
    print("   Continuing with basic file existence checks only...\n")


def extract_text_from_pdf(pdf_path: Path, max_pages: int = 3) -> str:
    """Extract text from first few pages of PDF."""
    if not PYPDF2_AVAILABLE:
        return ""
    
    try:
        reader = PdfReader(str(pdf_path))
        texts = []
        for page in reader.pages[:max_pages]:
            try:
                text = page.extract_text() or ""
                texts.append(text)
            except Exception:
                continue
        return "\n".join(texts)
    except Exception as e:
        print(f"   ⚠️  PDF reading error: {e}")
        return ""


def validate_pdf(pdf_path: Path, expected_doi: str) -> bool:
    """Check if PDF contains the expected DOI."""
    if not pdf_path.exists():
        return False
    
    text = extract_text_from_pdf(pdf_path)
    if not text:
        return None  # Can't validate
    
    return expected_doi.lower() in text.lower()


# Map of downloaded files to expected DOIs
DOWNLOADS_TO_CHECK = {
    "10.1016_j.cell.2023.11.034.pdf": "10.1016/j.cell.2023.11.034",
    "10.48550_arXiv.2311.12345.pdf": "10.48550/arXiv.2311.12345",
    "10.1126_science.adk4561.pdf": "10.1126/science.adk4561",
    "10.1126_science.adj6231.pdf": "10.1126/science.adj6231",
}


def main():
    """Run validation on downloaded PDFs."""
    print("="*70)
    print("PDF DOWNLOAD VALIDATION")
    print("="*70)
    print()
    
    downloads_dir = Path.home() / "Downloads"
    
    if not PYPDF2_AVAILABLE:
        print("Cannot perform DOI validation without PyPDF2.\n")
        return
    
    found_issues = False
    checked = 0
    
    for filename, expected_doi in DOWNLOADS_TO_CHECK.items():
        pdf_path = downloads_dir / filename
        
        print(f"Checking: {filename}")
        print(f"  Expected DOI: {expected_doi}")
        
        if not pdf_path.exists():
            print(f"  ⚠️  File not found at {pdf_path}")
            print()
            continue
        
        checked += 1
        size_mb = pdf_path.stat().st_size / (1024 * 1024)
        print(f"  File size: {size_mb:.1f} MB")
        
        result = validate_pdf(pdf_path, expected_doi)
        
        if result is True:
            print(f"  ✅ VALID - DOI found in PDF")
        elif result is False:
            print(f"  ❌ INVALID - DOI NOT found in PDF (WRONG PAPER!)")
            found_issues = True
        else:
            print(f"  ⚠️  Could not validate (PDF parsing failed)")
        
        print()
    
    print("="*70)
    if checked == 0:
        print("No files found to validate.")
    elif found_issues:
        print("⚠️  ISSUES FOUND - Some PDFs do not contain expected DOIs!")
        print("   These files may be wrong papers or corrupted.")
    else:
        print(f"✅ All {checked} checked PDFs appear valid!")
    print("="*70)


if __name__ == "__main__":
    main()
