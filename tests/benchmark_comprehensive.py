#!/usr/bin/env python3
"""
Comprehensive Real-World Benchmark for Paper Finder

Tests acquisition across:
- Multiple disciplines: Biology, Chemistry, Physics, Philosophy, Computer Science
- Different time periods: 1905-2024 (classic to recent)
- Different access types: Open Access, Preprints, Paywalled, Shadow Libraries
- Different publishers: Nature, Science, ACS, PLOS, IEEE, Wiley, Elsevier
- Edge cases: Malformed inputs, URLs, ISBNs

All DOIs verified as real and existing as of December 2024.
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
# All DOIs verified to exist as of December 2024
TEST_CASES = [
    # ========================================================================
    # OPEN ACCESS - PLOS ONE (always open, various disciplines)
    # ========================================================================
    
    TestCase(
        id="oa_plos_biology",
        reference="10.1371/journal.pone.0134116",
        category="Open Access - Biology",
        expected_result="success",
        description="PLOS ONE 2015 - Evolution of stomach acidity",
        expected_doi="10.1371/journal.pone.0134116"
    ),
    
    TestCase(
        id="oa_plos_education",
        reference="10.1371/journal.pone.0286208",
        category="Open Access - Education",
        expected_result="success",
        description="PLOS ONE 2023 - Cognitive flexibility study protocol",
        expected_doi="10.1371/journal.pone.0286208"
    ),
    
    TestCase(
        id="oa_plos_technology",
        reference="10.1371/journal.pone.0286112",
        category="Open Access - Education Tech",
        expected_result="success",
        description="PLOS ONE 2023 - ICT integration in education",
        expected_doi="10.1371/journal.pone.0286112"
    ),
    
    TestCase(
        id="oa_plos_health",
        reference="10.1371/journal.pone.0284420",
        category="Open Access - Health",
        expected_result="success",
        description="PLOS ONE 2023 - Spinal cord injury survey",
        expected_doi="10.1371/journal.pone.0284420"
    ),
    
    
    # ========================================================================
    # PREPRINTS - Direct PDF downloads (arXiv, bioRxiv)
    # ========================================================================
    
    TestCase(
        id="arxiv_cs",
        reference="10.48550/arXiv.2006.11239",
        category="Preprint - Computer Science",
        expected_result="success",
        description="arXiv 2020 - Language models",
        expected_doi="10.48550/arXiv.2006.11239"
    ),
    
    TestCase(
        id="arxiv_physics",
        reference="10.48550/arXiv.1706.03762",
        category="Preprint - AI/ML",
        expected_result="success",
        description="arXiv 2017 - Attention is All You Need (Transformer)",
        expected_doi="10.48550/arXiv.1706.03762"
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
    # CHEMISTRY - Classic papers (likely in shadow libraries)
    # ========================================================================
    
    TestCase(
        id="chem_woodward_hoffmann",
        reference="10.1021/ja01080a054",
        category="Chemistry - Classic",
        expected_result="success",
        description="JACS 1965 - Woodward-Hoffmann rules",
        expected_doi="10.1021/ja01080a054"
    ),
    
    TestCase(
        id="chem_hammond",
        reference="10.1021/ja01616a027",
        category="Chemistry - Classic",
        expected_result="success",
        description="JACS 1955 - Hammond postulate",
        expected_doi="10.1021/ja01616a027"
    ),
    
    TestCase(
        id="chem_grubbs",
        reference="10.1021/ja00074a086",
        category="Chemistry - Classic",
        expected_result="success",
        description="JACS 1993 - Grubbs ruthenium catalyst for olefin metathesis",
        expected_doi="10.1021/ja00074a086"
    ),
    
    TestCase(
        id="chem_messy_input",
        reference="ja01080a054https://pubs.acs.org/doi/10.1021/ja01080a054",
        category="Chemistry - Edge Case",
        expected_result="success",
        description="Woodward-Hoffmann with messy GUI paste",
        expected_doi="10.1021/ja01080a054"
    ),
    
    
    # ========================================================================
    # BIOLOGY - Classic landmark papers
    # ========================================================================
    
    TestCase(
        id="bio_watson_crick",
        reference="10.1038/171737a0",
        category="Biology - Classic",
        expected_result="success",
        description="Nature 1953 - DNA double helix structure",
        expected_doi="10.1038/171737a0"
    ),
    
    TestCase(
        id="bio_krebs_cycle",
        reference="10.1042/bj0320108",
        category="Biology - Classic",
        expected_result="success",  # Available on Sci-Hub
        description="Biochem J 1937 - Krebs cycle",
        expected_doi="10.1042/bj0320108"
    ),
    
    TestCase(
        id="bio_pcr",
        reference="10.1126/science.2448875",
        category="Biology - Classic",
        expected_result="success",
        description="Science 1987 - PCR technique",
        expected_doi="10.1126/science.2448875"
    ),
    
    
    # ========================================================================
    # PHYSICS - Classic papers
    # ========================================================================
    
    TestCase(
        id="physics_dirac",
        reference="10.1098/rspa.1928.0023",
        category="Physics - Classic",
        expected_result="success",
        description="Proc Royal Soc 1928 - Dirac equation",
        expected_doi="10.1098/rspa.1928.0023"
    ),
    
    TestCase(
        id="physics_einstein",
        reference="10.1002/andp.19053220607",
        category="Physics - Classic",
        expected_result="success",
        description="Annalen der Physik 1905 - Special relativity",
        expected_doi="10.1002/andp.19053220607"
    ),
    
    
    # ========================================================================
    # PHILOSOPHY - Recent papers (may be paywalled)
    # ========================================================================
    
    TestCase(
        id="phil_ethics",
        reference="10.1111/ejop.12955",
        category="Philosophy - Recent",
        expected_result="success",  # Actually OA with direct PDF
        description="European Journal of Philosophy 2024 - Krasimira Filcheva",
        expected_doi="10.1111/ejop.12955"
    ),
    
    TestCase(
        id="phil_political",
        reference="10.1111/jopp.12190",
        category="Philosophy - Recent",
        expected_result="failure",
        description="Journal of Political Philosophy 2023 - Valid DOI",
        expected_doi="10.1111/jopp.12190"
    ),
    
    
    # ========================================================================
    # RECENT PAYWALLED - Too new for shadow libraries
    # ========================================================================
    
    TestCase(
        id="recent_nature_2024",
        reference="10.1038/s41586-024-07487-w",
        category="Recent Paywalled - Biology",
        expected_result="failure",
        description="Nature 2024 - AlphaFold3",
        expected_doi="10.1038/s41586-024-07487-w"
    ),
    
    TestCase(
        id="recent_science_2024",
        reference="10.1126/science.adl2520",
        category="Recent Paywalled - Biology",
        expected_result="failure",
        description="Science 2024 - RoseTTAFold All-Atom",
        expected_doi="10.1126/science.adl2520"
    ),
    
    TestCase(
        id="recent_cell_2024",
        reference="10.1016/j.cell.2024.07.027",
        category="Recent Paywalled - Biology",
        expected_result="failure",
        description="Cell 2024 - Antimicrobial peptides",
        expected_doi="10.1016/j.cell.2024.07.027"
    ),
    
    
    # ========================================================================
    # BOOKS - ISBN resolution
    # ========================================================================
    
    TestCase(
        id="book_kuhn",
        reference="978-0226458083",
        category="Book - Philosophy",
        expected_result="oa_browser",
        description="Kuhn - Structure of Scientific Revolutions",
        expected_doi=None
    ),
    
    TestCase(
        id="book_popper",
        reference="978-0415278447",
        category="Book - Philosophy",
        expected_result="oa_browser",
        description="Popper - Logic of Scientific Discovery",
        expected_doi=None
    ),
    
    TestCase(
        id="book_darwin",
        reference="978-0451529060",
        category="Book - Biology",
        expected_result="success",
        description="Darwin - Origin of Species (public domain)",
        expected_doi=None
    ),
    
    
    # ========================================================================
    # MULTIDISCIPLINARY - Nature Methods, Biotech
    # ========================================================================
    
    TestCase(
        id="biotech_methods",
        reference="10.1038/s41592-024-02591-1",
        category="Biotechnology - Recent",
        expected_result="failure",
        description="Nature Methods 2024 - Year in review",
        expected_doi="10.1038/s41592-024-02591-1"
    ),
    
    TestCase(
        id="biotech_review",
        reference="10.1038/s41587-024-02508-5",
        category="Biotechnology - Recent",
        expected_result="failure",
        description="Nature Biotechnology 2024 - Research review",
        expected_doi="10.1038/s41587-024-02508-5"
    ),
    
    
    # ========================================================================
    # EDGE CASES - Testing robustness
    # ========================================================================
    
    TestCase(
        id="invalid_doi",
        reference="10.1234/FAKE.DOI.12345",
        category="Edge Case",
        expected_result="failure",
        description="Non-existent DOI",
        expected_doi=None
    ),
    
    TestCase(
        id="malformed_doi",
        reference="not-a-doi-at-all",
        category="Edge Case",
        expected_result="failure",
        description="Malformed DOI format",
        expected_doi=None
    ),
    
    TestCase(
        id="doi_with_url",
        reference="https://doi.org/10.1371/journal.pone.0134116",
        category="Edge Case - URL Input",
        expected_result="success",
        description="DOI provided as full URL",
        expected_doi="10.1371/journal.pone.0134116"
    ),
]


def run_test_case(test: TestCase, finder: PaperFinder, output_dir: Path) -> TestResult:
    """Run a single test case and return result."""
    print(f"\n{'='*70}")
    print(f"TEST: {test.id}")
    print(f"Reference: {test.reference}")
    print(f"Category: {test.category}")
    print(f"Description: {test.description}")
    print(f"Expected: {test.expected_result}")
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
        
        # Print summary with expectation check
        expected = test.expected_result
        actual = "success" if result.success else "failure"
        matches_expected = (expected == actual) or (expected == "oa_browser" and actual == "success")
        
        status_symbol = "✅" if matches_expected else "⚠️"
        
        if result.success:
            print(f"{status_symbol} SUCCESS via {result.source} ({elapsed:.1f}s)")
            if result.filepath:
                print(f"   File: {result.filepath.name}")
        else:
            print(f"{status_symbol} FAILED ({elapsed:.1f}s)")
            if result.error:
                print(f"   Error: {result.error}")
        
        if not matches_expected:
            print(f"   ⚠️  Expected: {expected}, Got: {actual}")
        
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
            by_category[cat] = {"total": 0, "success": 0, "failed": 0, "times": []}
        by_category[cat]["total"] += 1
        by_category[cat]["times"].append(result.time_seconds)
        if result.success:
            by_category[cat]["success"] += 1
        else:
            by_category[cat]["failed"] += 1
    
    # Build report
    total_time = sum(r.time_seconds for r in results)
    successes = sum(1 for r in results if r.success)
    failures = len(results) - successes
    
    report_lines = [
        "# Paper Finder - Comprehensive Benchmark Report",
        f"\n**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n## Summary Statistics",
        f"\n**Total Tests**: {len(results)}",
        f"**Successes**: {successes} ({100 * successes / len(results):.1f}%)",
        f"**Failures**: {failures} ({100 * failures / len(results):.1f}%)",
        f"**Total Time**: {total_time:.1f}s",
        f"**Average Time**: {total_time / len(results):.1f}s per test",
        "\n## Results by Category\n"
    ]
    
    for cat, stats in sorted(by_category.items()):
        success_rate = 100 * stats["success"] / stats["total"] if stats["total"] > 0 else 0
        avg_time = sum(stats["times"]) / len(stats["times"]) if stats["times"] else 0
        report_lines.append(
            f"- **{cat}**: {stats['success']}/{stats['total']} "
            f"({success_rate:.0f}% success, avg {avg_time:.1f}s)"
        )
    
    # Breakdown by expected vs actual
    report_lines.append("\n## Analysis")
    report_lines.append("\n### Expected Successes")
    expected_success = [r for r in results if r.success and 
                       any(tc.id == r.test_id and tc.expected_result in ["success", "oa_browser"] 
                           for tc in TEST_CASES)]
    report_lines.append(f"- {len(expected_success)} tests succeeded as expected")
    
    report_lines.append("\n### Expected Failures")
    expected_failure = [r for r in results if not r.success and 
                       any(tc.id == r.test_id and tc.expected_result == "failure" 
                           for tc in TEST_CASES)]
    report_lines.append(f"- {len(expected_failure)} tests failed as expected")
    
    report_lines.append("\n### Unexpected Results")
    unexpected = [r for r in results if not any(
        (tc.id == r.test_id and 
         ((tc.expected_result in ["success", "oa_browser"] and r.success) or
          (tc.expected_result == "failure" and not r.success)))
        for tc in TEST_CASES)]
    if unexpected:
        report_lines.append(f"- ⚠️  {len(unexpected)} unexpected results:")
        for r in unexpected:
            tc = next(tc for tc in TEST_CASES if tc.id == r.test_id)
            report_lines.append(f"  - `{r.test_id}`: Expected {tc.expected_result}, "
                              f"got {'success' if r.success else 'failure'}")
    else:
        report_lines.append("- ✅ All results matched expectations!")
    
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
    print("PAPER FINDER - COMPREHENSIVE BENCHMARK TEST SUITE")
    print("="*70)
    print(f"\nTest Coverage:")
    print(f"  • Biology, Chemistry, Physics, Philosophy, CS")
    print(f"  • Time span: 1905-2024")
    print(f"  • Open Access, Preprints, Classic Papers, Recent Paywalled")
    print(f"  • Multiple publishers: Nature, Science, ACS, PLOS, etc.")
    print(f"  • Edge cases: Malformed inputs, URLs, ISBNs")
    
    # Setup
    output_dir = Path("test_downloads_comprehensive")
    output_dir.mkdir(exist_ok=True)
    
    report_file = Path("benchmark_report_comprehensive.md")
    
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
    total_time = sum(r.time_seconds for r in results)
    
    print(f"\n{'='*70}")
    print("FINAL RESULTS")
    print(f"{'='*70}")
    print(f"✅ Successes: {successes}/{len(results)} ({100*successes/len(results):.1f}%)")
    print(f"❌ Failures: {failures}/{len(results)} ({100*failures/len(results):.1f}%)")
    print(f"⏱️  Total Time: {total_time:.1f}s")
    print(f"📊 Average: {total_time/len(results):.1f}s per test")
    print(f"\n📄 Full report: {report_file}")
    print("\n✅ Benchmark complete!")


if __name__ == "__main__":
    main()
