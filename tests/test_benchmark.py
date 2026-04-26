#!/usr/bin/env python3
"""
Automated benchmark test suite for Paper Finder.

Tests acquisition across different paper types, validates results,
and generates a detailed report with success/failure analysis.
"""

import sys
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime

# Ensure project root (where paper_finder.py lives) is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper_finder import PaperFinder


@dataclass
class TestCase:
    """A single test case for paper acquisition."""
    id: str
    reference: str
    category: str
    expected_result: str  # "success", "oa_browser", "failure"
    description: str
    expected_doi: Optional[str] = None  # For validation
    
    
@dataclass
class TestResult:
    """Result of running a test case."""
    test_id: str
    reference: str
    category: str
    success: bool
    source: str
    time_seconds: float
    error: Optional[str] = None
    filepath: Optional[Path] = None
    doi_validated: Optional[bool] = None  # True if PDF contains expected DOI
    notes: str = ""


# Test suite configuration
TEST_CASES = [
    # Open Access (should succeed via browser)
    TestCase(
        id="oa_nature_2024",
        reference="10.1038/s41586-023-06999-1",
        category="Open Access",
        expected_result="oa_browser",
        description="Nature 2024 OA paper",
        expected_doi="10.1038/s41586-023-06999-1"
    ),
    TestCase(
        id="oa_nature_freq",
        reference="10.1038/s41586-024-07354-8",
        category="Open Access",
        expected_result="oa_browser",
        description="Nature 2024 OA - frequent disturbances",
        expected_doi="10.1038/s41586-024-07354-8"
    ),
    TestCase(
        id="oa_scielo",
        reference="10.1590/S0103-50532013005000001",
        category="Open Access - International",
        expected_result="oa_browser",
        description="SciELO Brazil",
        expected_doi="10.1590/S0103-50532013005000001"
    ),
    
    # Should download (repositories, preprints)
    TestCase(
        id="cell_dataverse",
        reference="10.1016/j.cell.2023.11.034",
        category="Repository Download",
        expected_result="success",
        description="Cell 2024 via Dataverse",
        expected_doi="10.1016/j.cell.2023.11.034"
    ),
    TestCase(
        id="arxiv_preprint",
        reference="10.48550/arXiv.2311.12345",
        category="Preprint",
        expected_result="success",
        description="arXiv preprint",
        expected_doi="10.48550/arXiv.2311.12345"
    ),
    TestCase(
        id="biorxiv_preprint",
        reference="10.1101/2023.07.04.547696",
        category="Preprint",
        expected_result="success",
        description="bioRxiv preprint",
        expected_doi="10.1101/2023.07.04.547696"
    ),
    
    # Books (should open in browser or download)
    TestCase(
        id="book_elsevier",
        reference="978-0-12-822248-5",
        category="Book (ISBN)",
        expected_result="oa_browser",
        description="Elsevier book via Anna's Archive",
        expected_doi=None  # Books don't have DOIs
    ),
    
    # Paywalled recent (likely to fail or need shadow libraries)
    TestCase(
        id="paywalled_science_1",
        reference="10.1126/science.adk4561",
        category="Paywalled Recent",
        expected_result="failure",
        description="Science 2023 paywalled",
        expected_doi="10.1126/science.adk4561"
    ),
    TestCase(
        id="paywalled_science_2",
        reference="10.1126/science.adj6231",
        category="Paywalled Recent",
        expected_result="failure",
        description="Science 2023 paywalled",
        expected_doi="10.1126/science.adj6231"
    ),
    
    # Edge cases
    TestCase(
        id="fake_doi",
        reference="10.1021/FAKE_DOI_123",
        category="Edge Case",
        expected_result="failure",
        description="Invalid DOI (should fail gracefully)",
        expected_doi=None
    ),
    
    # Classic old papers (should work via LibGen/Anna's Archive)
    TestCase(
        id="classic_jacs_1951",
        reference="10.1021/ja01152a043",
        category="Historical",
        expected_result="success",
        description="JACS 1951",
        expected_doi="10.1021/ja01152a043"
    ),
]


def validate_pdf_doi(pdf_path: Path, expected_doi: str) -> bool:
    """
    Validate that a downloaded PDF actually contains the expected DOI.
    
    Returns:
        True if DOI found in PDF, False otherwise, None if validation unavailable
    """
    if not pdf_path.exists():
        return False
    
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return None  # Can't validate without PyPDF2
    
    try:
        reader = PdfReader(str(pdf_path))
        # Check first 3 pages
        for page in reader.pages[:3]:
            try:
                text = page.extract_text() or ""
                if expected_doi.lower() in text.lower():
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return None  # PDF corrupted or unreadable


def run_test_case(test: TestCase, finder: PaperFinder, output_dir: Path) -> TestResult:
    """Run a single test case and return result."""
    print(f"\n{'='*70}")
    print(f"TEST: {test.id}")
    print(f"Reference: {test.reference}")
    print(f"Category: {test.category}")
    print(f"Description: {test.description}")
    print(f"{'='*70}")
    
    start_time = time.time()
    
    try:
        # Run acquisition
        result = finder.find(test.reference, output_dir=output_dir)
        elapsed = time.time() - start_time
        
        # Validate PDF contains expected DOI (if applicable)
        doi_validated = None
        if result.success and result.filepath and test.expected_doi:
            doi_validated = validate_pdf_doi(result.filepath, test.expected_doi)
            if doi_validated is False:
                print(f"⚠️  WARNING: PDF does NOT contain expected DOI {test.expected_doi}")
        
        # Build result
        test_result = TestResult(
            test_id=test.id,
            reference=test.reference,
            category=test.category,
            success=result.success,
            source=result.source or "Unknown",
            time_seconds=round(elapsed, 1),
            error=result.error if not result.success else None,
            filepath=result.filepath,
            doi_validated=doi_validated
        )
        
        # Print summary
        if result.success:
            status_icon = "✅" if doi_validated != False else "⚠️"
            print(f"{status_icon} SUCCESS via {result.source} ({elapsed:.1f}s)")
            if result.filepath:
                print(f"   File: {result.filepath.name}")
            if doi_validated is True:
                print(f"   ✓ DOI validated in PDF")
            elif doi_validated is False:
                print(f"   ✗ DOI NOT found in PDF (WRONG PAPER!)")
        else:
            print(f"❌ FAILED ({elapsed:.1f}s)")
            if result.error:
                print(f"   Error: {result.error}")
        
        return test_result
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ EXCEPTION: {type(e).__name__}: {e}")
        return TestResult(
            test_id=test.id,
            reference=test.reference,
            category=test.category,
            success=False,
            source="Exception",
            time_seconds=round(elapsed, 1),
            error=f"{type(e).__name__}: {str(e)}"
        )


def generate_report(results: List[TestResult], output_file: Path):
    """Generate detailed test report."""
    
    # Calculate statistics by category
    by_category = {}
    for result in results:
        cat = result.category
        if cat not in by_category:
            by_category[cat] = {"total": 0, "success": 0, "failed": 0}
        by_category[cat]["total"] += 1
        if result.success:
            by_category[cat]["success"] += 1
        else:
            by_category[cat]["failed"] += 1
    
    # Build report
    report_lines = [
        "# Paper Finder - Automated Benchmark Report",
        f"\n**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n**Total Tests**: {len(results)}",
        f"**Successes**: {sum(1 for r in results if r.success)}",
        f"**Failures**: {sum(1 for r in results if not r.success)}",
        f"**Success Rate**: {100 * sum(1 for r in results if r.success) / len(results):.1f}%",
        "\n## Results by Category\n"
    ]
    
    for cat, stats in sorted(by_category.items()):
        success_rate = 100 * stats["success"] / stats["total"] if stats["total"] > 0 else 0
        report_lines.append(
            f"- **{cat}**: {stats['success']}/{stats['total']} "
            f"({success_rate:.0f}% success)"
        )
    
    report_lines.append("\n## Detailed Results\n")
    
    for result in results:
        status = "✅ PASS" if result.success else "❌ FAIL"
        report_lines.append(f"### {result.test_id} - {status}\n")
        report_lines.append(f"- **Reference**: `{result.reference}`")
        report_lines.append(f"- **Category**: {result.category}")
        report_lines.append(f"- **Source**: {result.source}")
        report_lines.append(f"- **Time**: {result.time_seconds}s")
        
        if result.doi_validated is not None:
            if result.doi_validated:
                report_lines.append(f"- **DOI Validation**: ✓ Correct paper")
            else:
                report_lines.append(f"- **DOI Validation**: ✗ **WRONG PAPER!**")
        
        if result.filepath:
            report_lines.append(f"- **File**: `{result.filepath.name}`")
        
        if result.error:
            report_lines.append(f"- **Error**: {result.error}")
        
        if result.notes:
            report_lines.append(f"- **Notes**: {result.notes}")
        
        report_lines.append("")  # Empty line between tests
    
    # Write report
    output_file.write_text("\n".join(report_lines))
    print(f"\n📊 Report saved to: {output_file}")


def main():
    """Run benchmark test suite."""
    print("="*70)
    print("PAPER FINDER - AUTOMATED BENCHMARK TEST SUITE")
    print("="*70)
    
    # Setup
    output_dir = Path("test_downloads")
    output_dir.mkdir(exist_ok=True)
    
    report_file = Path("benchmark_report.md")
    
    # Initialize finder
    print("\n🔧 Initializing Paper Finder...")
    finder = PaperFinder(silent_init=True)
    
    # Run tests
    print(f"\n🧪 Running {len(TEST_CASES)} test cases...\n")
    results = []
    
    for i, test in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}]", end=" ")
        result = run_test_case(test, finder, output_dir)
        results.append(result)
        
        # Brief pause between tests to avoid rate limits
        if i < len(TEST_CASES):
            time.sleep(2)
    
    # Generate report
    print("\n" + "="*70)
    print("GENERATING REPORT")
    print("="*70)
    
    generate_report(results, report_file)
    
    # Summary
    successes = sum(1 for r in results if r.success)
    failures = len(results) - successes
    
    print(f"\n✅ Successes: {successes}/{len(results)}")
    print(f"❌ Failures: {failures}/{len(results)}")
    print(f"📊 Success Rate: {100 * successes / len(results):.1f}%")
    
    # Check for wrong papers
    wrong_papers = [r for r in results if r.doi_validated is False]
    if wrong_papers:
        print(f"\n⚠️  WARNING: {len(wrong_papers)} test(s) returned WRONG paper:")
        for r in wrong_papers:
            print(f"   - {r.test_id}: {r.reference}")
    
    print(f"\n📄 Full report: {report_file}")
    print("\n✅ Benchmark complete!")


if __name__ == "__main__":
    main()
