#!/usr/bin/env python3
"""
Acquisition pipeline orchestration.

Manages the execution of multiple acquisition methods with:
- Method registration and ordering
- Parallel execution for independent sources
- Smart caching for method reordering
- Cancellation support
- Result aggregation
"""

import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass

from .result import AcquisitionResult
from .config import Config
from .metadata import MetadataResolver
from .validation import validate_pdf, validate_pdf_matches_metadata


@dataclass
class SourceMethod:
    """Represents a single acquisition source method."""
    name: str
    function: Callable
    tier: str  # 'fast', 'medium', or 'slow'
    enabled: bool = True


class AcquisitionPipeline:
    """
    Main orchestrator for paper acquisition.
    
    Coordinates multiple sources with intelligent fallback,
    parallel execution, and caching.
    """
    
    def __init__(
        self,
        config: Config = None,
        metadata_resolver: MetadataResolver = None,
        cache = None  # SmartCache instance
    ):
        """
        Initialize pipeline.
        
        Args:
            config: Configuration object
            metadata_resolver: MetadataResolver instance
            cache: SmartCache instance for method ordering
        """
        from .config import get_config
        
        self.config = config or get_config()
        self.metadata_resolver = metadata_resolver or MetadataResolver()
        self.cache = cache
        
        # Registered sources
        self.sources: List[SourceMethod] = []
        
        # Cancellation flag
        self._cancel_requested = False
        
        # Browser opened flag (stop searching if OA paper opened)
        self._browser_opened = False
    
    def register_source(
        self,
        name: str,
        function: Callable,
        tier: str = 'medium',
        enabled: bool = True
    ):
        """
        Register an acquisition source.
        
        Args:
            name: Human-readable name
            function: Callable that takes (doi, output_file, metadata) -> bool
            tier: 'fast', 'medium', or 'slow'
            enabled: Whether this source is enabled
        """
        if tier not in ['fast', 'medium', 'slow']:
            raise ValueError(f"Invalid tier: {tier}. Must be 'fast', 'medium', or 'slow'")
        
        source = SourceMethod(
            name=name,
            function=function,
            tier=tier,
            enabled=enabled
        )
        
        self.sources.append(source)
    
    def request_cancel(self):
        """Request immediate cancellation of current execution."""
        self._cancel_requested = True
    
    def _reset_cancel(self):
        """Reset cancellation flag."""
        self._cancel_requested = False
        self._browser_opened = False
    
    def _check_cancel(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancel_requested
    
    def execute(
        self,
        doi: str,
        output_file: Path,
        metadata: Dict,
        progress_callback: Callable[[str, str], None] = None
    ) -> AcquisitionResult:
        """
        Execute acquisition pipeline.
        
        Args:
            doi: DOI to acquire
            output_file: Where to save PDF
            metadata: Paper metadata
            progress_callback: Optional callback(stage, message) for progress updates
        
        Returns:
            AcquisitionResult with success status
        """
        start_time = time.time()
        self._reset_cancel()
        
        # Track attempts
        attempts: Dict[str, str] = {}
        
        # Early cancellation check
        if self._cancel_requested:
            return AcquisitionResult(
                success=False,
                error="Cancelled by user",
                metadata=metadata,
                attempts=attempts
            )
        
        # Group sources by tier
        fast_sources = [s for s in self.sources if s.tier == 'fast' and s.enabled]
        medium_sources = [s for s in self.sources if s.tier == 'medium' and s.enabled]
        slow_sources = [s for s in self.sources if s.tier == 'slow' and s.enabled]
        
        # Apply cache-based reordering if available
        if self.cache and metadata.get('publisher') and metadata.get('year'):
            publisher = metadata['publisher']
            year = metadata['year']
            
            # Get best methods for this publisher
            best_methods = self.cache.get_best_methods(publisher, top_n=3)
            
            if best_methods:
                if progress_callback:
                    progress_callback("Cache", f"Prioritizing methods based on {publisher} history")
                
                # Reorder each tier based on cache
                fast_sources = self._reorder_by_cache(fast_sources, best_methods)
                medium_sources = self._reorder_by_cache(medium_sources, best_methods)
                slow_sources = self._reorder_by_cache(slow_sources, best_methods)
        
        # Execute in groups
        method_groups = [
            ("Fast Sources", fast_sources),
            ("Medium Sources", medium_sources),
            ("Deep Sources", slow_sources)
        ]
        
        # Try each group
        for group_name, group_sources in method_groups:
            if not group_sources:
                continue
            
            if self._cancel_requested:
                break
            
            if self._browser_opened:
                # Browser was opened for OA paper - stop searching
                break
            
            elapsed = time.time() - start_time
            if progress_callback:
                progress_callback(group_name, f"Trying {len(group_sources)} methods... ({elapsed:.1f}s elapsed)")
            else:
                print(f"\n[{group_name}] - Running {len(group_sources)} methods in parallel...")
                print(f"  [{elapsed:.1f}s elapsed]")
            
            # Execute group in parallel
            result = self._execute_group(
                group_sources,
                doi,
                output_file,
                metadata,
                progress_callback
            )
            
            if result and result.success:
                total_time = time.time() - start_time
                
                if progress_callback:
                    progress_callback("Success", f"Paper acquired via {result.source} ({total_time:.1f}s)")
                else:
                    print(f"\n✓ Success via {result.source} (total: {total_time:.1f}s)")
                
                return result
        
        # All methods failed
        total_time = time.time() - start_time
        
        if self._cancel_requested:
            error = "Cancelled by user"
        elif self._browser_opened:
            # Browser was opened but no PDF downloaded
            return AcquisitionResult(
                success=True,
                source="Open Access (Browser)",
                filepath=None,
                metadata=metadata,
                attempts={"Open Access (Browser)": "opened in browser"}
            )
        else:
            error = "All acquisition methods failed"
        
        if progress_callback:
            progress_callback("Failed", f"{error} ({total_time:.1f}s)")
        else:
            print(f"\n✗ {error} (total: {total_time:.1f}s)")
        
        return AcquisitionResult(
            success=False,
            error=error,
            metadata=metadata,
            attempts=attempts
        )
    
    def _reorder_by_cache(
        self,
        sources: List[SourceMethod],
        best_methods: List[str]
    ) -> List[SourceMethod]:
        """
        Reorder sources based on cache results.
        
        Args:
            sources: List of sources to reorder
            best_methods: List of method names sorted by success rate
        
        Returns:
            Reordered list of sources
        """
        # Create priority map
        priority = {name: i for i, name in enumerate(best_methods)}
        
        # Sort sources by priority (methods in best_methods first)
        def sort_key(source: SourceMethod) -> Tuple[int, str]:
            if source.name in priority:
                return (0, priority[source.name])  # High priority
            else:
                return (1, source.name)  # Low priority (alphabetical)
        
        return sorted(sources, key=sort_key)
    
    def _execute_group(
        self,
        sources: List[SourceMethod],
        doi: str,
        output_file: Path,
        metadata: Dict,
        progress_callback: Callable[[str, str], None] = None
    ) -> Optional[AcquisitionResult]:
        """
        Execute a group of sources in parallel.
        
        Args:
            sources: List of sources to try
            doi: DOI to acquire
            output_file: Output file path
            metadata: Paper metadata
            progress_callback: Progress callback
        
        Returns:
            AcquisitionResult if successful, None otherwise
        """
        # Check if parallel executor is available
        try:
            from src.integrations.parallel_executor import execute_parallel_pipeline
            use_parallel = self.config.pipeline.parallel_execution
        except ImportError:
            use_parallel = False
        
        if use_parallel and len(sources) > 1:
            # Use parallel execution
            return self._execute_parallel(
                sources,
                doi,
                output_file,
                metadata,
                progress_callback
            )
        else:
            # Fallback to sequential execution
            return self._execute_sequential(
                sources,
                doi,
                output_file,
                metadata,
                progress_callback
            )
    
    def _execute_parallel(
        self,
        sources: List[SourceMethod],
        doi: str,
        output_file: Path,
        metadata: Dict,
        progress_callback: Callable[[str, str], None] = None
    ) -> Optional[AcquisitionResult]:
        """Execute sources in parallel using ThreadPoolExecutor."""
        import concurrent.futures
        
        # Create wrapper functions that handle caching and cancellation
        def make_wrapper(source: SourceMethod):
            def wrapper():
                # Check cancellation before starting
                if self._cancel_requested or self._browser_opened:
                    return None
                
                try:
                    method_start = time.time()
                    
                    # CRITICAL FIX: Use temp file to avoid parallel sources corrupting each other
                    import tempfile
                    import shutil
                    temp_file = Path(tempfile.mktemp(suffix='.pdf', prefix=f'paperfinder_{source.name.replace(" ", "_")}_'))
                    
                    # Execute the source method with temp file
                    success = source.function(doi, temp_file, metadata)
                    
                    method_time = time.time() - method_start
                    
                    # Record in cache (only if not cancelled)
                    if not self._cancel_requested and self.cache:
                        try:
                            if metadata.get('publisher') and metadata.get('year'):
                                self.cache.record_attempt(
                                    metadata['publisher'],
                                    metadata['year'],
                                    source.name,
                                    success
                                )
                        except Exception as cache_err:
                            # Don't let cache failures break the pipeline
                            pass
                    
                    if success and not self._cancel_requested:
                        # SPECIAL CASE: If source is browser-based opening, we don't expect a file
                        if "Browser" in source.name or getattr(self, '_browser_opened', False):
                            print(f"  ✓ {source.name} succeeded (browser opened)")
                            return AcquisitionResult(
                                success=True,
                                source=source.name,
                                filepath=None,  # No file created
                                metadata=metadata,
                                attempts={source.name: "success (browser)"}
                            )

                        # Validate temp file exists and has content
                        file_exists = temp_file.exists()
                        file_size = temp_file.stat().st_size if file_exists else 0
                        file_valid = file_exists and file_size > 1000
                        
                        if not file_valid:
                            # Source claimed success but temp file is invalid
                            print(f"  ⚠ {source.name} succeeded but file validation failed (exists={file_exists}, size={file_size})")
                            # Clean up invalid temp file
                            if temp_file.exists():
                                temp_file.unlink()
                            return None
                        
                        # Smart content validation: title + DOI + source type
                        try:
                            matches = validate_pdf_matches_metadata(
                                temp_file,
                                metadata,
                                doi,
                                source.name,
                            )
                        except Exception:
                            matches = True  # Fail open on validation error
                        
                        if not matches:
                            print(f"  ✗ {source.name} returned WRONG paper (metadata/content mismatch)")
                            if temp_file.exists():
                                temp_file.unlink()
                            return None
                        
                        # SUCCESS! Copy temp file to final output location (atomic)
                        try:
                            shutil.move(str(temp_file), str(output_file))
                        except Exception as e:
                            print(f"  ⚠ {source.name} failed to move temp file: {e}")
                            if temp_file.exists():
                                temp_file.unlink()
                            return None
                        
                        if progress_callback:
                            progress_callback(source.name, f"Success in {method_time:.1f}s")
                        else:
                            print(f"  ✓ {source.name} succeeded in {method_time:.1f}s")
                        
                        # Return result
                        return AcquisitionResult(
                            success=True,
                            source=source.name,
                            filepath=output_file,
                            metadata=metadata,
                            attempts={source.name: "success"}
                        )
                    else:
                        # Source failed - clean up temp file
                        try:
                            if temp_file.exists():
                                temp_file.unlink()
                        except:
                            pass
                    
                    return None
                    
                except Exception as e:
                    # Clean up temp file on exception
                    try:
                        if temp_file.exists():
                            temp_file.unlink()
                    except:
                        pass
                    
                    if not self._cancel_requested:
                        if self.cache:
                            if metadata.get('publisher') and metadata.get('year'):
                                self.cache.record_attempt(
                                    metadata['publisher'],
                                    metadata['year'],
                                    source.name,
                                    False
                                )
                        
                        if progress_callback:
                            progress_callback(source.name, f"Failed: {type(e).__name__}")
                    
                    return None
            
            return wrapper
        
        # Execute in parallel
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.network.max_workers
        )
        
        try:
            future_to_source = {
                executor.submit(make_wrapper(source)): source
                for source in sources
            }
            
            group_start = time.time()
            
            # Wait for first success or all to complete
            while future_to_source:
                # Check for cancellation frequently
                if self._cancel_requested:
                    for f in future_to_source:
                        f.cancel()
                    return None
                
                # Check if browser was opened
                if self._browser_opened:
                    for f in future_to_source:
                        f.cancel()
                    return AcquisitionResult(
                        success=True,
                        source="Open Access (Browser)",
                        filepath=None,
                        metadata=metadata,
                        attempts={"Open Access (Browser)": "opened in browser"}
                    )
                
                # Wait briefly for any method to complete
                done, not_done = concurrent.futures.wait(
                    list(future_to_source.keys()),
                    timeout=0.2,
                    return_when=concurrent.futures.FIRST_COMPLETED
                )
                
                # Group timeout
                if time.time() - group_start > self.config.pipeline.method_timeout:
                    for f in future_to_source:
                        f.cancel()
                    break
                
                # No method finished yet; loop again
                if not done:
                    continue
                
                # Process completed methods
                for future in done:
                    source = future_to_source.pop(future)
                    
                    try:
                        if future.cancelled():
                            continue
                        
                        result = future.result()
                        
                        if result and result.success:
                            # Success! Cancel remaining
                            for f in not_done:
                                f.cancel()
                            
                            return result
                    
                    except Exception as e:
                        continue
        
        finally:
            executor.shutdown(wait=False)
        
        return None
    
    def _execute_sequential(
        self,
        sources: List[SourceMethod],
        doi: str,
        output_file: Path,
        metadata: Dict,
        progress_callback: Callable[[str, str], None] = None
    ) -> Optional[AcquisitionResult]:
        """Execute sources sequentially (fallback if parallel not available)."""
        for source in sources:
            if self._cancel_requested:
                break
                
            if self._browser_opened:
                return AcquisitionResult(
                    success=True,
                    source="Open Access (Browser)",
                    filepath=None,
                    metadata=metadata,
                    attempts={"Open Access (Browser)": "opened in browser"}
                )
            
            try:
                if progress_callback:
                    progress_callback(source.name, "Trying...")
                
                method_start = time.time()
                success = source.function(doi, output_file, metadata)
                method_time = time.time() - method_start
                
                if self._browser_opened:
                    return AcquisitionResult(
                        success=True,
                        source="Open Access (Browser)",
                        filepath=None,
                        metadata=metadata,
                        attempts={"Open Access (Browser)": "opened in browser"}
                    )
                
                # Record in cache
                if self.cache and metadata.get('publisher') and metadata.get('year'):
                    self.cache.record_attempt(
                        metadata['publisher'],
                        metadata['year'],
                        source.name,
                        success
                    )
                
                if success and not self._cancel_requested:
                    # Validate file exists and has content
                    file_valid = output_file.exists() and output_file.stat().st_size > 1000
                    
                    if not file_valid:
                        print(f"  ⚠ {source.name} succeeded but file validation failed")
                        continue
                    
                    try:
                        matches = validate_pdf_matches_metadata(
                            output_file,
                            metadata,
                            doi,
                            source.name,
                        )
                    except Exception:
                        matches = True
                        
                    if not matches:
                        print(f"  ✗ {source.name} returned WRONG paper (metadata/content mismatch)")
                        if output_file.exists():
                            output_file.unlink()
                        continue
                    
                    if progress_callback:
                        progress_callback(source.name, f"Success in {method_time:.1f}s")
                    
                    return AcquisitionResult(
                        success=True,
                        source=source.name,
                        filepath=output_file,
                        metadata=metadata,
                        attempts={source.name: "success"}
                    )
            
            except Exception as e:
                if self.cache and metadata.get('publisher') and metadata.get('year'):
                    self.cache.record_attempt(
                        metadata['publisher'],
                        metadata['year'],
                        source.name,
                        False
                    )
                
                continue
        
        return None
    
    def get_registered_sources(self) -> List[str]:
        """Get list of registered source names."""
        return [s.name for s in self.sources if s.enabled]
    
    def get_sources_by_tier(self, tier: str) -> List[str]:
        """Get list of source names in a specific tier."""
        return [s.name for s in self.sources if s.tier == tier and s.enabled]
    
    def disable_source(self, name: str):
        """Disable a source by name."""
        for source in self.sources:
            if source.name == name:
                source.enabled = False
                break
    
    def enable_source(self, name: str):
        """Enable a source by name."""
        for source in self.sources:
            if source.name == name:
                source.enabled = True
                break
