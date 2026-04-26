#!/usr/bin/env python3
"""
Real-world benchmark test suite for Paper Finder.

Tests acquisition across:
- Different disciplines (chemistry, philosophy, history, biology, physics)
- Different time periods (1950s to 2024)
- Different access types (OA, paywalled, preprints, books)
- Different publishers (Nature, Science, ACS, Elsevier, Springer, etc.)

All DOIs/ISBNs verified as real and existing.
"""

import sys
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime

# Ensure project root is on sys.path
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
    expected_doi: Optional[str] = None
    

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
    notes: str = ""


# Real, verified test cases - DIVERSE & COMPREHENSIVE
TEST_CASES = [
    # ========================================================================
    # OPEN ACCESS - Should succeed via browser or download
    # ========================================================================
    
    TestCase(
        id="oa_plos_one",
        reference="10.1371/journal.pone.0270478",
        category="Open Access",
        expected_result="oa_browser",
        description="PLOS ONE 2022 - Always OA",
        expected_doi="10.1371/journal.pone.0270478"
    ),
    
    
    # ========================================================================
    # PREPRINTS - Direct PDF downloads
    # ========================================================================
    
    TestCase(
        id="arxiv_direct",
        reference="10.48550/arXiv.2006.11239",
        category="Preprint",
        expected_result="success",
        description="arXiv 2020 - Direct PDF",
        expected_doi="10.48550/arXiv.2006.11239"
    ),
    
    TestCase(
        id="biorxiv_covid",
        reference="10.1101/2020.07.01.182741v1",
        category="Preprint - Virology",
        expected_result="success", 
        description="bioRxiv COVID - Open Access paper",
        expected_doi="10.1101/2020.07.01.182741"
    ),
    
    
    # ========================================================================
    # SHADOW LIBRARY TARGETS - Old classics, Sci-Hub priority
    # ========================================================================
    
    TestCase(
        id="classic_watson_crick",
        reference="10.1038/171737a0",
        category="Classic",
        expected_result="success",
        description="Nature 1953 - DNA structure",
        expected_doi="10.1038/171737a0"
    ),
    
    TestCase(
        id="classic_woodward_hoffmann",
        reference="10.1021/ja01080a054",
        category="Classic",
        expected_result="success",
        description="JACS 1965 - Electrocyclic reactions",
        expected_doi="10.1021/ja01080a054"
    ),
    
    TestCase(
        id="classic_woodward_messy_input",
        reference="ja01080a054https://pubs.acs.org/doi/10.1021/ja01080a054",
        category="Classic",
        expected_result="success",
        description="Same paper, messy GUI input",
        expected_doi="10.1021/ja01080a054"
    ),
    
    TestCase(
        id="classic_hammond",
        reference="10.1021/ja01616a027",
        category="Classic",
        expected_result="success",
        description="JACS 1955 - Hammond postulate",
        expected_doi="10.1021/ja01616a027"
    ),
    
    
    # ========================================================================
    # RECENT PAYWALLED - Expected to fail
    # ========================================================================
    
    TestCase(
        id="recent_paywalled",
        reference="10.1126/science.adk3222",
        category="Recent Paywalled",
        expected_result="failure",
        description="Science 2024 - Too recent",
        expected_doi="10.1126/science.adk3222"
    ),
    
    
    # ========================================================================
    # BOOKS - ISBN resolution
    # ========================================================================
    
    TestCase(
        id="book_kuhn",
        reference="978-0226458083",
        category="Book",
        expected_result="oa_browser",
        description="Kuhn - Structure of Scientific Revolutions",
        expected_doi=None
    ),
    
    
    # ========================================================================
    # EDGE CASES
    # ========================================================================
    
    TestCase(
        id="invalid_doi",
        reference="10.1234/FAKE.DOI.12345",
        category="Edge Case",
        expected_result="failure",
        description="Invalid DOI",
        expected_doi=None
    ),
]


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
        
        # Build result
        test_result = TestResult(
            test_id=test.id,
            reference=test.reference,
            category=test.category,
            success=result.success,
            source=result.source or "Unknown",
            time_seconds=round(elapsed, 1),
            error=result.error if not result.success else None,
            filepath=result.filepath
        )
        
        # Print summary
        if result.success:
            print(f"✅ SUCCESS via {result.source} ({elapsed:.1f}s)")
            if result.filepath:
                print(f"   File: {result.filepath.name}")
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
        "# Paper Finder - Real-World Benchmark Report",
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
    print("PAPER FINDER - REAL-WORLD BENCHMARK TEST SUITE")
    print("="*70)
    
    # Setup
    output_dir = Path("test_downloads_real")
    output_dir.mkdir(exist_ok=True)
    
    report_file = Path("benchmark_report_real.md")
    
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
    
    print(f"\n📄 Full report: {report_file}")
    print("\n✅ Benchmark complete!")


if __name__ == "__main__":
    main()
