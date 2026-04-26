#!/usr/bin/env python3
"""
Paper Finder Test Harness - Validate acquisition pipeline with real DOIs.

This tool allows you to:
1. Test multiple DOIs and track which sources succeed
2. Generate comparison reports (before/after improvements)
3. Build test corpus for regression testing
4. Measure performance improvements

Usage:
    # Test a single DOI
    python test_harness.py --doi 10.1126/science.abj8754
    
    # Test from file
    python test_harness.py --file test_dois.txt
    
    # Generate report
    python test_harness.py --file test_dois.txt --report results.json
    
    # Compare two runs
    python test_harness.py --compare before.json after.json
"""

import sys
import json
import time
import argparse
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass, asdict
import tempfile

from paper_finder import PaperFinder, DownloadResult


@dataclass
class TestResult:
    """Result of testing a single DOI."""
    doi: str
    success: bool
    source: str
    time_seconds: float
    error: str = ""
    attempts: Dict[str, str] = None
    metadata: Dict = None
    
    def to_dict(self):
        return asdict(self)


class TestHarness:
    """Test harness for Paper Finder."""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.finder = PaperFinder(silent_init=not verbose)
        self.results: List[TestResult] = []
    
    def test_doi(self, doi: str, output_dir: Path = None) -> TestResult:
        """Test a single DOI."""
        if output_dir is None:
            output_dir = Path(tempfile.mkdtemp())
        
        if self.verbose:
            print(f"\n{'='*70}")
            print(f"Testing: {doi}")
            print('='*70)
        
        start_time = time.time()
        
        try:
            result = self.finder.acquire(doi, output_dir=output_dir)
            elapsed = time.time() - start_time
            
            test_result = TestResult(
                doi=doi,
                success=result.success,
                source=result.source if result.success else "",
                time_seconds=round(elapsed, 2),
                error=result.error or "",
                attempts=result.attempts or {},
                metadata=result.metadata or {}
            )
            
            if self.verbose:
                if result.success:
                    print(f"\n✅ SUCCESS via {result.source} in {elapsed:.1f}s")
                else:
                    print(f"\n❌ FAILED after {elapsed:.1f}s: {result.error}")
            
        except Exception as e:
            elapsed = time.time() - start_time
            test_result = TestResult(
                doi=doi,
                success=False,
                source="",
                time_seconds=round(elapsed, 2),
                error=f"Exception: {type(e).__name__}: {str(e)}"
            )
            
            if self.verbose:
                print(f"\n❌ EXCEPTION after {elapsed:.1f}s: {e}")
        
        self.results.append(test_result)
        return test_result
    
    def test_file(self, file_path: Path) -> List[TestResult]:
        """Test multiple DOIs from a file (one per line)."""
        dois = []
        
        with open(file_path) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line and not line.startswith('#'):
                    dois.append(line)
        
        print(f"\n📋 Found {len(dois)} DOIs to test")
        
        results = []
        for i, doi in enumerate(dois, 1):
            print(f"\n[{i}/{len(dois)}]", end=" ")
            result = self.test_doi(doi)
            results.append(result)
        
        return results
    
    def generate_report(self, output_file: Path = None):
        """Generate JSON report of all test results."""
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_tests": len(self.results),
            "successful": sum(1 for r in self.results if r.success),
            "failed": sum(1 for r in self.results if not r.success),
            "success_rate": round(sum(1 for r in self.results if r.success) / len(self.results) * 100, 1) if self.results else 0,
            "avg_time_seconds": round(sum(r.time_seconds for r in self.results) / len(self.results), 2) if self.results else 0,
            "sources": self._analyze_sources(),
            "results": [r.to_dict() for r in self.results]
        }
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"\n📄 Report saved to: {output_file}")
        
        return report
    
    def _analyze_sources(self) -> Dict:
        """Analyze which sources were most successful."""
        source_stats = {}
        
        for result in self.results:
            if result.success and result.source:
                if result.source not in source_stats:
                    source_stats[result.source] = {
                        "count": 0,
                        "avg_time": 0,
                        "times": []
                    }
                source_stats[result.source]["count"] += 1
                source_stats[result.source]["times"].append(result.time_seconds)
        
        # Calculate averages
        for source, stats in source_stats.items():
            stats["avg_time"] = round(sum(stats["times"]) / len(stats["times"]), 2)
            del stats["times"]  # Remove raw times from output
        
        # Sort by count
        return dict(sorted(source_stats.items(), key=lambda x: x[1]["count"], reverse=True))
    
    def print_summary(self):
        """Print summary statistics."""
        if not self.results:
            print("\nNo results to summarize")
            return
        
        total = len(self.results)
        successful = sum(1 for r in self.results if r.success)
        failed = total - successful
        success_rate = successful / total * 100
        avg_time = sum(r.time_seconds for r in self.results) / total
        
        print("\n" + "="*70)
        print("📊 TEST SUMMARY")
        print("="*70)
        print(f"Total tests:    {total}")
        print(f"✅ Successful:   {successful} ({success_rate:.1f}%)")
        print(f"❌ Failed:       {failed} ({100-success_rate:.1f}%)")
        print(f"⏱️  Avg time:     {avg_time:.1f}s")
        
        # Source breakdown
        sources = self._analyze_sources()
        if sources:
            print("\n🎯 SUCCESS BY SOURCE:")
            for source, stats in sources.items():
                print(f"  {source:30s} {stats['count']:3d} papers  (avg {stats['avg_time']:.1f}s)")
        
        print("="*70)


def compare_reports(before_file: Path, after_file: Path):
    """Compare two test reports."""
    with open(before_file) as f:
        before = json.load(f)
    
    with open(after_file) as f:
        after = json.load(f)
    
    print("\n" + "="*70)
    print("📈 COMPARISON REPORT")
    print("="*70)
    
    print(f"\nBefore: {before['timestamp']}")
    print(f"After:  {after['timestamp']}")
    
    print(f"\n{'Metric':<30s} {'Before':>10s} {'After':>10s} {'Change':>10s}")
    print("-"*70)
    
    # Success rate
    before_rate = before['success_rate']
    after_rate = after['success_rate']
    change = after_rate - before_rate
    print(f"{'Success Rate (%)':<30s} {before_rate:>10.1f} {after_rate:>10.1f} {change:+10.1f}")
    
    # Avg time
    before_time = before['avg_time_seconds']
    after_time = after['avg_time_seconds']
    change = after_time - before_time
    speedup = before_time / after_time if after_time > 0 else 1.0
    print(f"{'Avg Time (s)':<30s} {before_time:>10.1f} {after_time:>10.1f} {change:+10.1f}")
    print(f"{'Speedup':<30s} {'':>10s} {speedup:>10.1f}x {'':>10s}")
    
    # Success/Failure counts
    print(f"\n{'Before':<30s} {before['successful']} successes / {before['failed']} failures")
    print(f"{'After':<30s} {after['successful']} successes / {after['failed']} failures")
    
    print("="*70)


def create_sample_test_file():
    """Create a sample test file with diverse DOIs."""
    sample_dois = """# Paper Finder Test Corpus
# Format: One DOI per line, comments start with #

# Old papers (pre-2010) - should have high success rate
10.1126/science.283.5400.381
10.1038/35057062
10.1021/ja00051a040

# Recent papers (2020+) - challenging
10.1126/science.abj8754
10.1038/s41586-023-06139-9
10.1021/jacs.3c00908

# Open Access papers - should always work
10.1371/journal.pone.0123456
10.3389/fmicb.2020.00001

# Book chapters - test Anna's Archive
10.1016/B978-0-443-27475-6.00019-X

# Add your own DOIs below:
"""
    
    output_file = Path("test_dois.txt")
    with open(output_file, 'w') as f:
        f.write(sample_dois)
    
    print(f"✅ Created sample test file: {output_file}")
    print("   Edit this file to add your own DOIs")


def main():
    parser = argparse.ArgumentParser(
        description="Test harness for Paper Finder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('--doi', help='Single DOI to test')
    parser.add_argument('--file', help='File with DOIs (one per line)', type=Path)
    parser.add_argument('--report', help='Output report file (JSON)', type=Path)
    parser.add_argument('--compare', nargs=2, metavar=('BEFORE', 'AFTER'),
                       help='Compare two report files', type=Path)
    parser.add_argument('--create-sample', action='store_true',
                       help='Create sample test_dois.txt file')
    parser.add_argument('--quiet', action='store_true',
                       help='Suppress verbose output')
    
    args = parser.parse_args()
    
    # Create sample file
    if args.create_sample:
        create_sample_test_file()
        return 0
    
    # Compare reports
    if args.compare:
        compare_reports(args.compare[0], args.compare[1])
        return 0
    
    # Run tests
    harness = TestHarness(verbose=not args.quiet)
    
    if args.doi:
        harness.test_doi(args.doi)
    elif args.file:
        harness.test_file(args.file)
    else:
        parser.print_help()
        return 1
    
    # Print summary
    harness.print_summary()
    
    # Generate report
    if args.report:
        harness.generate_report(args.report)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
