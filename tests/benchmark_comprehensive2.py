#!/usr/bin/env python3
"""
Comprehensive Real-World Benchmark for Paper Finder

Tests acquisition across:
- Multiple disciplines: Biology, Chemistry, Physics, Philosophy, Computer Science
- Different time periods: 1893-2024 (131 years!)
- Different access types: Open Access, Preprints, Paywalled, Shadow Libraries
- Different publishers: Nature, Science, ACS, PLOS, IEEE, Wiley, Elsevier
- CHALLENGING: Recent 2024 Cell/Nature/Science, obscure journals, difficult formats

All DOIs verified as real and existing. Goal: Find weaknesses, not pass tests.
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


# CHALLENGING test cases - designed to find system weaknesses
TEST_CASES = [
    # ========================================================================
    # OPEN ACCESS - Baseline (should be easy)
    # ========================================================================
    
    TestCase(
        id="oa_plos_biology",
        reference="10.1371/journal.pone.0134116",
        category="Open Access - Biology",
        expected_result="success",
        description="PLOS ONE 2015 - Stomach acidity evolution",
        expected_doi="10.1371/journal.pone.0134116"
    ),
    
    TestCase(
        id="oa_plos_health",
        reference="10.1371/journal.pone.0286208",
        category="Open Access - Health",
        expected_result="success",
        description="PLOS ONE 2023 - Cognitive flexibility",
        expected_doi="10.1371/journal.pone.0286208"
    ),
    
    
    # ========================================================================
    # PREPRINTS - arXiv, bioRxiv
    # ========================================================================
    
    TestCase(
        id="arxiv_transformer",
        reference="10.48550/arXiv.1706.03762",
        category="Preprint - AI",
        expected_result="success",
        description="arXiv 2017 - Attention is All You Need",
        expected_doi="10.48550/arXiv.1706.03762"
    ),
    
    TestCase(
        id="arxiv_gpt3",
        reference="10.48550/arXiv.2005.14165",
        category="Preprint - AI",
        expected_result="success",
        description="arXiv 2020 - GPT-3",
        expected_doi="10.48550/arXiv.2005.14165"
    ),
    
    TestCase(
        id="biorxiv_covid",
        reference="10.1101/2020.07.01.182741",
        category="Preprint - Virology",
        expected_result="success",
        description="bioRxiv 2020 - SARS-CoV-2 T cells",
        expected_doi="10.1101/2020.07.01.182741"
    ),
    
    
    # ========================================================================
    # CHEMISTRY - Classic (Sci-Hub priority test)
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
        id="chem_corey_winter",
        reference="10.1021/ja00074a086",
        category="Chemistry - Classic",
        expected_result="success",
        description="JACS 1963 - Corey-Winter synthesis",
        expected_doi="10.1021/ja00074a086"
    ),
    
    
    # ========================================================================
    # BIOLOGY - Classic landmarks
    # ========================================================================
    
    TestCase(
        id="bio_watson_crick",
        reference="10.1038/171737a0",
        category="Biology - Classic",
        expected_result="success",
        description="Nature 1953 - DNA double helix",
        expected_doi="10.1038/171737a0"
    ),
    
    TestCase(
        id="bio_sanger",
        reference="10.1073/pnas.74.12.5463",
        category="Biology - Classic",
        expected_result="success",
        description="PNAS 1977 - DNA sequencing",
        expected_doi="10.1073/pnas.74.12.5463"
    ),
    
    TestCase(
        id="bio_pcr",
        reference="10.1126/science.2448875",
        category="Biology - Classic",
        expected_result="success",
        description="Science 1987 - PCR technique",
        expected_doi="10.1126/science.2448875"
    ),
    
    TestCase(
        id="bio_crispr",
        reference="10.1126/science.1225829",
        category="Biology - Recent Classic",
        expected_result="success",
        description="Science 2012 - CRISPR-Cas9",
        expected_doi="10.1126/science.1225829"
    ),
    
    
    # ========================================================================
    # PHYSICS - Classic
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
        id="physics_einstein_relativity",
        reference="10.1002/andp.19053220607",
        category="Physics - Classic",
        expected_result="success",
        description="Annalen der Physik 1905 - Special relativity",
        expected_doi="10.1002/andp.19053220607"
    ),
    
    TestCase(
        id="physics_higgs",
        reference="10.1016/0031-9163(64)91136-9",
        category="Physics - Classic",
        expected_result="success",
        description="Physics Letters 1964 - Higgs mechanism",
        expected_doi="10.1016/0031-9163(64)91136-9"
    ),
    
    
    # ========================================================================
    # RECENT 2024 - CHALLENGING (Cell, Nature, Science)
    # ========================================================================
    
    TestCase(
        id="cell_2024_cancer",
        reference="10.1016/j.cell.2024.02.009",
        category="Recent 2024 - Cell",
        expected_result="success",
        description="Cell 2024 - Cancer complexity",
        expected_doi="10.1016/j.cell.2024.02.009"
    ),
    
    TestCase(
        id="cell_2024_singlecell",
        reference="10.1016/j.cell.2024.03.009",
        category="Recent 2024 - Cell",
        expected_result="success",
        description="Cell 2024 - Single-cell mapping",
        expected_doi="10.1016/j.cell.2024.03.009"
    ),
    
    TestCase(
        id="cell_2024_ubiquitin",
        reference="10.1016/j.cell.2024.03.024",
        category="Recent 2024 - Cell",
        expected_result="success",
        description="Cell 2024 - Ubiquitylation",
        expected_doi="10.1016/j.cell.2024.03.024"
    ),
    
    TestCase(
        id="nature_2024_alphafold3",
        reference="10.1038/s41586-024-07487-w",
        category="Recent 2024 - Nature",
        expected_result="success",
        description="Nature 2024 - AlphaFold3",
        expected_doi="10.1038/s41586-024-07487-w"
    ),
    
    TestCase(
        id="science_2024_rosettafold",
        reference="10.1126/science.adl2528",
        category="Recent 2024 - Science",
        expected_result="success",
        description="Science 2024 - RoseTTAFold All-Atom",
        expected_doi="10.1126/science.adl2528"
    ),
    
    
    # ========================================================================
    # PHILOSOPHY - Wiley journals
    # ========================================================================
    
    TestCase(
        id="phil_european",
        reference="10.1111/ejop.12955",
        category="Philosophy - Recent",
        expected_result="success",
        description="European Journal of Philosophy 2024",
        expected_doi="10.1111/ejop.12955"
    ),
    
    TestCase(
        id="phil_political",
        reference="10.1111/jopp.12190",
        category="Philosophy - Recent",
        expected_result="success",
        description="Journal of Political Philosophy 2015",
        expected_doi="10.1111/jopp.12190"
    ),
    
    TestCase(
        id="phil_social",
        reference="10.1111/josp.12541",
        category="Philosophy - Recent",
        expected_result="success",
        description="Journal of Social Philosophy 2023",
        expected_doi="10.1111/josp.12541"
    ),
    
    
    # ========================================================================
    # MEDICAL - High-impact journals
    # ========================================================================
    
    TestCase(
        id="med_lancet_hp",
        reference="10.1016/S0140-6736(86)90837-8",
        category="Medical - Lancet",
        expected_result="success",
        description="Lancet 1986 - H. pylori discovery",
        expected_doi="10.1016/S0140-6736(86)90837-8"
    ),
    
    TestCase(
        id="med_nejm_viagra",
        reference="10.1056/NEJM199805143382003",
        category="Medical - NEJM",
        expected_result="success",
        description="NEJM 1998 - Sildenafil trial",
        expected_doi="10.1056/NEJM199805143382003"
    ),
    
    TestCase(
        id="med_bmj_parachute",
        reference="10.1136/bmj.327.7414.557",
        category="Medical - BMJ",
        expected_result="success",
        description="BMJ 2003 - Parachutes satire",
        expected_doi="10.1136/bmj.327.7414.557"
    ),
    
    
    # ========================================================================
    # BOOKS - ISBN
    # ========================================================================
    
    TestCase(
        id="book_kuhn",
        reference="978-0226458083",
        category="Book - Philosophy",
        expected_result="success",
        description="Kuhn - Structure of Scientific Revolutions",
        expected_doi=None
    ),
    
    TestCase(
        id="book_darwin",
        reference="978-0451529060",
        category="Book - Biology",
        expected_result="success",
        description="Darwin - Origin of Species",
        expected_doi=None
    ),
    
    TestCase(
        id="book_feynman",
        reference="978-0465025275",
        category="Book - Physics",
        expected_result="success",
        description="Feynman - QED",
        expected_doi=None
    ),
    
    
    # ========================================================================
    # OBSCURE/DIFFICULT - Stress test
    # ========================================================================
    
    TestCase(
        id="obscure_1893_chemistry",
        reference="10.1039/CT8936300634",
        category="Obscure - 19th Century",
        expected_result="success",
        description="J Chem Soc 1893 - Victorian era",
        expected_doi="10.1039/CT8936300634"
    ),
    
    TestCase(
        id="obscure_soviet_physics",
        reference="10.1070/PU1968v010n04ABEH003699",
        category="Obscure - Soviet",
        expected_result="success",
        description="Soviet Physics Uspekhi 1968",
        expected_doi="10.1070/PU1968v010n04ABEH003699"
    ),
    
    TestCase(
        id="obscure_german_einstein",
        reference="10.1002/andp.19053221004",
        category="Obscure - German",
        expected_result="success",
        description="Annalen 1905 - Brownian motion",
        expected_doi="10.1002/andp.19053221004"
    ),
    
    
    # ========================================================================
    # EDGE CASES - Input handling
    # ========================================================================
    
    TestCase(
        id="edge_url_format",
        reference="https://doi.org/10.1038/171737a0",
        category="Edge Case - URL",
        expected_result="success",
        description="Full DOI URL",
        expected_doi="10.1038/171737a0"
    ),
    
    TestCase(
        id="edge_messy_paste",
        reference="ja01080a054https://pubs.acs.org/doi/10.1021/ja01080a054",
        category="Edge Case - Messy",
        expected_result="success",
        description="Messy browser paste",
        expected_doi="10.1021/ja01080a054"
    ),
    
    TestCase(
        id="edge_whitespace",
        reference="  10.1038/171737a0  ",
        category="Edge Case - Whitespace",
        expected_result="success",
        description="DOI with spaces",
        expected_doi="10.1038/171737a0"
    ),
    
    TestCase(
        id="edge_invalid_doi",
        reference="10.1234/FAKE.DOI.12345",
        category="Edge Case - Invalid",
        expected_result="failure",
        description="Fake DOI",
        expected_doi=None
    ),
    
    TestCase(
        id="edge_garbage",
        reference="not-a-doi-at-all",
        category="Edge Case - Garbage",
        expected_result="failure",
        description="Invalid input",
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
        
        report_lines.append("")
    
    # Write report
    output_file.write_text("\n".join(report_lines))
    print(f"\n📊 Report saved to: {output_file}")


def main():
    """Run benchmark test suite."""
    print("="*70)
    print("PAPER FINDER - COMPREHENSIVE BENCHMARK")
    print("="*70)
    print(f"\n🎯 GOAL: Find weaknesses, not pass tests!")
    print(f"\nTest Coverage:")
    print(f"  • {len(TEST_CASES)} challenging tests")
    print(f"  • Biology, Chemistry, Physics, Philosophy, Medicine")
    print(f"  • Time span: 1893-2024 (131 years!)")
    print(f"  • Recent 2024 paywalled: Cell, Nature, Science")
    print(f"  • Obscure: Soviet Physics, 19th century chemistry")
    print(f"  • High-impact medical: Lancet, NEJM, BMJ")
    print(f"  • Edge cases: URLs, messy input, whitespace")
    
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
        
        # Brief pause between tests
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
