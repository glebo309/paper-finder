#!/usr/bin/env python3
"""
Quick test to verify refactored Paper Finder system works.
Tests:
1. Identity resolution with new module
2. Direct DOI acquisition
3. arXiv fast-path
4. Title-based resolution
"""

import sys
from pathlib import Path
import tempfile

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper_finder import PaperFinder
from src.core.identity import IdentityResolver


def test_identity_resolution():
    """Test the new identity resolution module."""
    print("\n" + "="*60)
    print("Testing Identity Resolution")
    print("="*60)
    
    resolver = IdentityResolver()
    
    # Test DOI extraction
    test_cases = [
        ("10.1038/nature12373", "doi"),
        ("https://doi.org/10.1038/nature12373", "doi"),
        ("arXiv:2311.12345", "arxiv"),
        ("978-0-226-458083", "isbn"),
        ("10.1101/2023.07.04.547696", "doi"),  # bioRxiv
        ("Watson Crick DNA structure Nature 1953", "title"),
    ]
    
    for ref, expected_type in test_cases:
        print(f"\n[Test] {ref}")
        record = resolver.resolve(ref)
        id_type = record.get("identifier", {}).get("type")
        id_value = record.get("identifier", {}).get("value")
        print(f"  → Type: {id_type}, Value: {id_value}")
        
        if expected_type == "title":
            # Title resolution might return doi if found via Crossref
            assert id_type in ["title", "doi"], f"Expected title or doi, got {id_type}"
        else:
            assert id_type == expected_type, f"Expected {expected_type}, got {id_type}"
        
        if id_type != "unknown":
            print(f"  ✓ Successfully resolved to {id_type}")
    
    print("\n✅ All identity resolution tests passed!")


def test_paper_acquisition():
    """Test actual paper acquisition with tiered sources."""
    print("\n" + "="*60)
    print("Testing Paper Acquisition")
    print("="*60)
    
    finder = PaperFinder(silent_init=True)
    
    # Create temp directory for downloads
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        
        # Test cases (fast, reliable ones)
        test_refs = [
            # arXiv - should use fast-path
            ("10.48550/arXiv.2006.11239", "arXiv"),
            # bioRxiv - should use fast-path
            ("10.1101/2020.12.08.416727", "bioRxiv"),
            # Older paper - might find via Sci-Hub
            ("10.1038/171737a0", "Nature 1953"),
        ]
        
        for ref, description in test_refs:
            print(f"\n[Test] {description}: {ref}")
            
            result = finder.find(ref, output_dir)
            
            if result.success:
                print(f"  ✓ Success via: {result.source}")
                if result.filepath and result.filepath.exists():
                    size_kb = result.filepath.stat().st_size / 1024
                    print(f"    Downloaded: {size_kb:.1f} KB")
            else:
                print(f"  ✗ Failed: {result.error}")
                print(f"    Attempts: {result.attempts}")
    
    print("\n✅ Acquisition tests completed!")


def main():
    """Run all tests."""
    print("Testing Refactored Paper Finder System")
    print("="*60)
    
    # Test identity resolution first
    test_identity_resolution()
    
    # Then test acquisition
    test_paper_acquisition()
    
    print("\n" + "="*60)
    print("All tests completed successfully!")
    print("="*60)


if __name__ == "__main__":
    main()
