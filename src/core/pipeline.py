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
from .validation import verify_document_identity


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
        progress_callback: Callable[[str, str], None] = None,
        exclude_sources=()
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
        # The caller resets cancellation when starting a new user operation.
        # Do not erase a Stop request arriving between identification and here.
        output_file = Path(output_file)
        attempts = {}
        if output_file.exists():
            return AcquisitionResult(success=False, error="Output file already exists",
                                     metadata=metadata, attempts=attempts)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        for tier in ("fast", "medium", "slow"):
            if self._cancel_requested:
                break
            sources = [source for source in self.sources if source.enabled and source.tier == tier and source.name not in exclude_sources]
            if self.cache and metadata.get("publisher"):
                try:
                    sources = self._reorder_by_cache(sources, self.cache.get_best_methods(metadata["publisher"], top_n=3))
                except Exception:
                    pass  # Cache is an optimization, never evidence of identity.
            if not sources:
                continue
            if progress_callback:
                progress_callback(tier.title() + " Sources", f"Trying {len(sources)} methods")
            result = self._execute_group(sources, doi, output_file, metadata, progress_callback)
            attempts.update(result.attempts)
            if result.success:
                result.attempts = attempts
                return result
        error = "Cancelled by user" if self._cancel_requested else "No verified PDF acquired"
        if any("browser" in str(value).lower() for value in attempts.values()):
            error += "; a page was opened in the browser"
        return AcquisitionResult(success=False, error=error, metadata=metadata, attempts=attempts)

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
    
    def _execute_group(self, sources, doi, output_file, metadata, progress_callback=None):
        workers = max(1, min(int(self.config.network.max_workers), len(sources)))
        if not self.config.pipeline.parallel_execution:
            workers = 1
        return self._run_sources(sources, doi, output_file, metadata, progress_callback, workers)

    def _execute_parallel(self, sources, doi, output_file, metadata, progress_callback=None):
        return self._run_sources(sources, doi, output_file, metadata, progress_callback,
                                 max(1, min(int(self.config.network.max_workers), len(sources))))

    def _execute_sequential(self, sources, doi, output_file, metadata, progress_callback=None):
        return self._run_sources(sources, doi, output_file, metadata, progress_callback, 1)

    def _run_sources(self, sources, doi, output_file, metadata, progress_callback, workers):
        """Workers own temporary files; only the coordinator publishes one winner.

        Source callables must enforce their own I/O timeouts: Python cannot kill an
        in-flight thread. Late completions can only remove their temporary file,
        never write the public output. Browser navigation is not acquisition.
        """
        import concurrent.futures
        import os
        import tempfile
        import threading

        stop = threading.Event()
        attempts = {}
        output_file = Path(output_file)
        record = dict(metadata)
        if doi:
            record["doi"] = doi

        def cleanup(path):
            if path:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

        def attempt(source):
            path = None
            keep = False
            try:
                if stop.is_set() or self._cancel_requested:
                    return {"status": "cancelled", "path": None}
                fd, name = tempfile.mkstemp(suffix=".pdf", prefix=".paperfinder-", dir=output_file.parent)
                os.close(fd)
                path = Path(name)
                success = source.function(doi, path, dict(metadata))
                if stop.is_set() or self._cancel_requested:
                    return {"status": "cancelled", "path": None}
                if not success:
                    return {"status": "failed", "path": None}
                if not path.exists() or not path.stat().st_size:
                    status = "opened in browser; no PDF" if "browser" in source.name.lower() or self._browser_opened else "source returned no PDF"
                    return {"status": status, "path": None}
                try:
                    verification = verify_document_identity(path, record)
                except Exception as exc:
                    verification = {"status": "unverifiable", "reasons": [type(exc).__name__]}
                status = verification.get("status", "unverifiable")
                if status != "verified":
                    return {"status": status + ": " + "; ".join(verification.get("reasons", [])), "path": None}
                keep = True
                return {"status": "verified", "path": path}
            except Exception as exc:
                return {"status": "failed: " + type(exc).__name__, "path": None}
            finally:
                if not keep or stop.is_set() or self._cancel_requested:
                    cleanup(path)

        def cleanup_late(future):
            if stop.is_set() and not future.cancelled():
                try:
                    cleanup(future.result().get("path"))
                except Exception:
                    pass

        def cache_attempt(source, success):
            if self.cache and metadata.get("publisher") and metadata.get("year"):
                try:
                    self.cache.record_attempt(metadata["publisher"], metadata["year"], source.name, success)
                except Exception:
                    pass

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        pending = {}
        all_futures = []
        deadline = time.monotonic() + max(0, float(self.config.pipeline.method_timeout))
        try:
            for source in sources:
                future = executor.submit(attempt, source)
                future.add_done_callback(cleanup_late)
                pending[future] = source
                all_futures.append(future)
            while pending and not self._cancel_requested:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                done, _ = concurrent.futures.wait(pending, timeout=min(.1, remaining),
                                                  return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    source = pending.pop(future)
                    item = future.result()
                    attempts[source.name] = item["status"]
                    path = item.get("path")
                    if self._cancel_requested:
                        cleanup(path)
                        break
                    if item["status"] != "verified":
                        cache_attempt(source, False)
                        continue
                    try:
                        # A hard link publishes the whole same-filesystem file in
                        # one operation and refuses to overwrite existing output.
                        os.link(path, output_file)
                    except OSError as exc:
                        attempts[source.name] = "publish failed: " + type(exc).__name__
                        cache_attempt(source, False)
                        continue
                    finally:
                        cleanup(path)
                    cache_attempt(source, True)
                    attempts[source.name] = "verified"
                    for other_source in pending.values():
                        attempts.setdefault(other_source.name, "cancelled after verified result")
                    if progress_callback:
                        progress_callback(source.name, "Verified PDF acquired")
                    return AcquisitionResult(success=True, source=source.name,
                                             filepath=output_file, metadata=metadata, attempts=attempts)
            for source in pending.values():
                attempts.setdefault(source.name, "cancelled" if self._cancel_requested else "timed out")
            return AcquisitionResult(success=False, error="No verified PDF in this source group",
                                     metadata=metadata, attempts=attempts)
        finally:
            stop.set()
            for future in all_futures:
                future.cancel()
                cleanup_late(future) if future.done() else None
            executor.shutdown(wait=False, cancel_futures=True)

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
