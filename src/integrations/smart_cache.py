#!/usr/bin/env python3
"""
Smart caching system that learns which methods work for which publishers.

Over time, this will reorder methods to try the most successful ones first.
"""

import json
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Dict


class SmartCache:
    """Learn and cache which acquisition methods work best for each publisher."""
    
    def __init__(self, cache_file: Path = None):
        if cache_file is None:
            cache_file = Path.home() / ".paper_finder_cache.json"
        
        self.cache_file = cache_file
        self.stats = self._load_stats()
    
    def _load_stats(self) -> Dict:
        """Load statistics from cache file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    return json.load(f)
            except:
                pass
        
        return {
            "publisher_success": defaultdict(lambda: defaultdict(int)),
            "year_success": defaultdict(lambda: defaultdict(int)),
            "total_attempts": 0,
            "total_successes": 0
        }
    
    def _save_stats(self):
        """Save statistics to cache file."""
        try:
            # Convert defaultdicts to regular dicts for JSON
            save_data = {
                "publisher_success": dict(self.stats["publisher_success"]),
                "year_success": dict(self.stats["year_success"]),
                "total_attempts": self.stats["total_attempts"],
                "total_successes": self.stats["total_successes"]
            }
            
            with open(self.cache_file, 'w') as f:
                json.dump(save_data, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}")
    
    def record_attempt(self, publisher: str, year: int, method: str, success: bool):
        """Record an acquisition attempt."""
        self.stats["total_attempts"] += 1
        
        if success:
            self.stats["total_successes"] += 1
            self.stats["publisher_success"][publisher][method] += 1
            
            # Categorize by year range
            if year:
                if year >= 2020:
                    year_range = "2020+"
                elif year >= 2010:
                    year_range = "2010-2019"
                elif year >= 2000:
                    year_range = "2000-2009"
                else:
                    year_range = "pre-2000"
                
                self.stats["year_success"][year_range][method] += 1
        
        self._save_stats()
    
    def get_best_methods(self, publisher: str, top_n: int = 3) -> List[str]:
        """Get top N methods for this publisher based on historical success."""
        methods = self.stats["publisher_success"].get(publisher, {})
        
        if not methods:
            return []
        
        # Sort by success count
        sorted_methods = sorted(methods.items(), key=lambda x: x[1], reverse=True)
        return [method for method, count in sorted_methods[:top_n]]
    
    def get_best_methods_by_year(self, year: int, top_n: int = 3) -> List[str]:
        """Get top N methods for papers from this year range."""
        if year >= 2020:
            year_range = "2020+"
        elif year >= 2010:
            year_range = "2010-2019"
        elif year >= 2000:
            year_range = "2000-2009"
        else:
            year_range = "pre-2000"
        
        methods = self.stats["year_success"].get(year_range, {})
        
        if not methods:
            return []
        
        sorted_methods = sorted(methods.items(), key=lambda x: x[1], reverse=True)
        return [method for method, count in sorted_methods[:top_n]]
    
    def reorder_methods(
        self, 
        methods: List[Tuple[str, any]], 
        publisher: str = None,
        year: int = None
    ) -> List[Tuple[str, any]]:
        """
        Reorder methods based on historical success.
        
        Args:
            methods: List of (method_name, method_func) tuples
            publisher: Publisher name (e.g., "springer", "elsevier")
            year: Publication year
        
        Returns:
            Reordered list with best methods first
        """
        # Get best methods for this context
        best_methods = []
        
        if publisher:
            best_methods.extend(self.get_best_methods(publisher, top_n=3))
        
        if year:
            best_methods.extend(self.get_best_methods_by_year(year, top_n=3))
        
        if not best_methods:
            return methods  # No data yet, use default order
        
        # Reorder: best methods first, then the rest
        reordered = []
        remaining = []
        
        for method in methods:
            method_name = method[0]
            if method_name in best_methods:
                reordered.append(method)
            else:
                remaining.append(method)
        
        # Sort best methods by their success count
        reordered.sort(key=lambda m: best_methods.index(m[0]) if m[0] in best_methods else 999)
        
        return reordered + remaining
    
    def get_stats_summary(self) -> str:
        """Get a human-readable summary of cache statistics."""
        total = self.stats["total_attempts"]
        success = self.stats["total_successes"]
        rate = (success / total * 100) if total > 0 else 0
        
        summary = [
            f"Smart Cache Statistics",
            f"=" * 40,
            f"Total attempts: {total}",
            f"Total successes: {success}",
            f"Success rate: {rate:.1f}%",
            f"",
            f"Top methods by publisher:",
        ]
        
        for publisher, methods in self.stats["publisher_success"].items():
            if methods:
                top = sorted(methods.items(), key=lambda x: x[1], reverse=True)[0]
                summary.append(f"  {publisher}: {top[0]} ({top[1]} successes)")
        
        return "\n".join(summary)


# Global cache instance
_cache = None

def get_cache() -> SmartCache:
    """Get the global cache instance."""
    global _cache
    if _cache is None:
        _cache = SmartCache()
    return _cache
