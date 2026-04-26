#!/usr/bin/env python3
"""
Parallel execution engine for paper acquisition methods.

Runs multiple methods simultaneously to maximize speed.
"""

import concurrent.futures
from typing import List, Tuple, Callable, Optional, Dict
from pathlib import Path
import time


class ParallelExecutor:
    """Execute acquisition methods in parallel groups."""
    
    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
    
    def execute_group(
        self, 
        methods: List[Tuple[str, Callable]], 
        timeout: int = 60
    ) -> Optional[Tuple[str, bool]]:
        """
        Execute a group of methods in parallel.
        
        Returns (method_name, True) on first success, or None if all fail.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all methods
            future_to_method = {
                executor.submit(method_func): method_name 
                for method_name, method_func in methods
            }
            
            try:
                # Wait for first success or all to complete
                for future in concurrent.futures.as_completed(future_to_method, timeout=timeout):
                    method_name = future_to_method[future]
                    
                    try:
                        result = future.result()
                        if result:  # Success!
                            # Cancel remaining futures
                            for f in future_to_method:
                                if f != future:
                                    f.cancel()
                            
                            return (method_name, True)
                    
                    except Exception as e:
                        print(f"  {method_name} error: {type(e).__name__}")
                        continue
            
            except concurrent.futures.TimeoutError:
                print(f"  Group timeout after {timeout}s")
                # Cancel all remaining
                for future in future_to_method:
                    future.cancel()
        
        return None
    
    def execute_sequential_groups(
        self,
        groups: List[Tuple[str, List[Tuple[str, Callable]]]],
        group_timeout: int = 60
    ) -> Optional[Tuple[str, str]]:
        """
        Execute groups sequentially, but methods within each group in parallel.
        
        Args:
            groups: List of (group_name, methods) tuples
            group_timeout: Timeout per group in seconds
        
        Returns:
            (group_name, method_name) on success, or None if all fail
        """
        for group_name, methods in groups:
            print(f"\n[{group_name}]")
            
            result = self.execute_group(methods, timeout=group_timeout)
            
            if result:
                method_name, success = result
                return (group_name, method_name)
        
        return None


def create_method_groups(
    doi: str,
    output_file: Path,
    meta: Dict,
    all_methods: Dict[str, Callable]
) -> List[Tuple[str, List[Tuple[str, Callable]]]]:
    """
    Organize methods into parallel execution groups.
    
    Group 1 (Fast & High Success): OA, SciHub, LibGen
    Group 2 (Medium Speed): Crossref, Semantic Scholar, PMC, Landing Page, Advanced Bypass
    Group 3 (Slow): International, Google Scholar, Multi-lang, Chinese, Deep Crawl
    """
    
    # Helper to create bound method
    def make_method(func):
        return lambda: func(doi, output_file, meta)
    
    groups = [
        ("Fast Sources", [
            ("Open Access", make_method(all_methods["oa"])),
            ("SciHub", make_method(all_methods["scihub"])),
            ("LibGen", make_method(all_methods["libgen"])),
        ]),
        
        ("Medium Sources", [
            ("Crossref Direct", make_method(all_methods["crossref"])),
            ("Semantic Scholar", make_method(all_methods["semantic"])),
            ("PubMed Central", make_method(all_methods["pmc"])),
            ("Landing Page", make_method(all_methods["landing"])),
            ("Advanced Bypass", make_method(all_methods["bypass"])),
        ]),
        
        ("Deep Sources", [
            ("International", make_method(all_methods["international"])),
            ("Google Scholar", make_method(all_methods["scholar"])),
            ("Multi-language", make_method(all_methods["multilang"])),
            ("Chinese Sources", make_method(all_methods["chinese"])),
            ("Deep Crawl", make_method(all_methods["deep"])),
        ])
    ]
    
    return groups


def execute_parallel_pipeline(
    doi: str,
    output_file: Path,
    meta: Dict,
    all_methods: Dict[str, Callable],
    max_workers: int = 3
) -> Optional[str]:
    """
    Execute the full acquisition pipeline with parallel execution.
    
    Returns:
        Source name if successful, None otherwise
    """
    executor = ParallelExecutor(max_workers=max_workers)
    
    # Create method groups
    groups = create_method_groups(doi, output_file, meta, all_methods)
    
    # Execute
    result = executor.execute_sequential_groups(groups, group_timeout=60)
    
    if result:
        group_name, method_name = result
        return method_name
    
    return None
