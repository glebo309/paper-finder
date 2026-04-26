#!/usr/bin/env python3
"""
Test improvements: Parallel execution, smart caching, enhanced Crossref, Unpaywall V2
"""

from pathlib import Path
from paper_finder import PaperFinder
import time

# Test cases
test_cases = [
    {
        "name": "Old paper (fast via SciHub/LibGen)",
        "doi": "10.1126/science.283.5400.381",
        "expected": "SciHub or LibGen (parallel)"
    },
    {
        "name": "Open Access (should try all locations)",
        "doi": "10.1371/journal.pone.0030373",
        "expected": "Open Access (Unpaywall V2)"
    },
    {
        "name": "Recent paper (challenging)",
        "doi": "10.1038/s41586-023-06415-8",
        "expected": "May fail (paywalled)"
    }
]

def test_improvements():
    """Test the new improvements."""
    print("=" * 80)
    print("TESTING NEW IMPROVEMENTS")
    print("=" * 80)
    
    finder = PaperFinder()
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)
    
    results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n[{i}/{len(test_cases)}] {test['name']}")
        print(f"DOI: {test['doi']}")
        print(f"Expected: {test['expected']}")
        print("-" * 80)
        
        try:
            result = finder.find(test['doi'], output_dir=output_dir)
            
            if result.success:
                print(f"\n✅ SUCCESS via {result.source}")
                results.append((test['name'], "SUCCESS", result.source))
                # Clean up
                if result.filepath and result.filepath.exists():
                    result.filepath.unlink()
            else:
                print(f"\n❌ FAILED: {result.error}")
                results.append((test['name'], "FAILED", result.error))
        
        except Exception as e:
            print(f"\n❌ ERROR: {type(e).__name__}: {e}")
            results.append((test['name'], "ERROR", str(e)))
        
        print("-" * 80)
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    for name, status, detail in results:
        if status == "SUCCESS":
            print(f"✅ {name}: {detail}")
        else:
            print(f"❌ {name}: {status}")
    
    success_count = sum(1 for _, status, _ in results if status == "SUCCESS")
    print(f"\nSuccess Rate: {success_count}/{len(results)} ({100*success_count/len(results):.0f}%)")

if __name__ == "__main__":
    test_improvements()
