#!/usr/bin/env python3
"""
Test the new enhancement modules (preprints, repositories, publisher-specific).

This script tests difficult cases that should benefit from the new capabilities.
"""

from pathlib import Path
from paper_finder import PaperFinder
import time

# Test cases specifically for new enhancements
test_cases = [
    {
        "name": "Recent physics paper (arXiv preprint should exist)",
        "doi": "10.1103/PhysRevLett.131.010801",
        "expected": "Should find via arXiv in Preprints module"
    },
    {
        "name": "Recent bioRxiv paper",
        "doi": "10.1101/2023.09.01.555965",
        "expected": "Should find via bioRxiv"
    },
    {
        "name": "Nature paper (try publisher tricks)",
        "doi": "10.1038/s41586-023-06415-8",
        "expected": "Should try Nature/Springer strategies"
    },
    {
        "name": "Wiley paper (try publisher tricks)",
        "doi": "10.1002/anie.202308240",
        "expected": "Should try Wiley epdf endpoints"
    },
    {
        "name": "Old reliable (should still work fast)",
        "doi": "10.1126/science.283.5400.381",
        "expected": "Should find via SciHub/LibGen quickly"
    }
]

def test_enhancements():
    """Test the new enhancement modules."""
    print("=" * 80)
    print("TESTING NEW ENHANCEMENT MODULES")
    print("=" * 80)
    print("\nModules being tested:")
    print("  1. Preprints Enhanced (arXiv, bioRxiv, medRxiv, chemRxiv, SSRN, etc.)")
    print("  2. Repositories (Zenodo, Figshare, OSF, institutional repos)")
    print("  3. Publisher Enhanced (Nature, Science, Elsevier, Wiley, IEEE, ACS)")
    print("=" * 80)
    
    finder = PaperFinder()
    output_dir = Path("test_enhancements_output")
    output_dir.mkdir(exist_ok=True)
    
    results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"[{i}/{len(test_cases)}] {test['name']}")
        print(f"DOI: {test['doi']}")
        print(f"Expected: {test['expected']}")
        print("-" * 80)
        
        start_time = time.time()
        
        try:
            result = finder.find(test['doi'], output_dir=output_dir)
            
            elapsed = time.time() - start_time
            
            if result.success:
                print(f"\n✅ SUCCESS via {result.source} ({elapsed:.1f}s)")
                results.append((test['name'], "SUCCESS", result.source, elapsed))
                
                # Clean up
                if result.filepath and result.filepath.exists():
                    size_mb = result.filepath.stat().st_size / (1024*1024)
                    print(f"   File size: {size_mb:.2f} MB")
                    result.filepath.unlink()
            else:
                print(f"\n❌ FAILED: {result.error} ({elapsed:.1f}s)")
                results.append((test['name'], "FAILED", result.error, elapsed))
        
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"\n❌ ERROR: {type(e).__name__}: {e} ({elapsed:.1f}s)")
            results.append((test['name'], "ERROR", str(e), elapsed))
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    total_time = 0
    for name, status, detail, elapsed in results:
        total_time += elapsed
        status_icon = "✅" if status == "SUCCESS" else "❌"
        print(f"{status_icon} {name}")
        print(f"   Status: {status}")
        print(f"   {detail}")
        print(f"   Time: {elapsed:.1f}s")
        print()
    
    success_count = sum(1 for _, status, _, _ in results if status == "SUCCESS")
    print(f"Success Rate: {success_count}/{len(results)} ({100*success_count/len(results):.0f}%)")
    print(f"Total Time: {total_time:.1f}s")
    print(f"Avg Time per Paper: {total_time/len(results):.1f}s")
    
    # Cleanup
    try:
        output_dir.rmdir()
    except:
        pass

if __name__ == "__main__":
    test_enhancements()
