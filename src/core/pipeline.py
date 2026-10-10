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
import threading
from copy import deepcopy
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass

from .result import AcquisitionResult
from .config import Config
from .metadata import MetadataResolver
from .validation import verify_document_identity


_worker_context = threading.local()


def current_operation_stop_event():
    """Return the latched stop event for this acquisition worker, if any."""
    return getattr(_worker_context, 'stop', None)


def operation_cancelled():
    event = current_operation_stop_event()
    return bool(event is not None and event.is_set())


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
        self._operation_stop = threading.Event()
        self._state_lock = threading.RLock()
        
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
        """Latch cancellation for the current operation and its running workers."""
        with self._state_lock:
            self._cancel_requested = True
            self._operation_stop.set()

    def _reset_cancel(self):
        """Begin fresh caller state without reviving an older worker's event."""
        with self._state_lock:
            self._operation_stop.set()
            self._operation_stop = threading.Event()
            self._cancel_requested = False
            self._browser_opened = False

    def _check_cancel(self):
        event = current_operation_stop_event()
        return event.is_set() if event is not None else self._operation_stop.is_set()

    def execute(self, doi, output_file, metadata, progress_callback=None,
                exclude_sources=(), additional_sources=(), verification_policies=None):
        """Race all enabled independent sources; publish only a verified winner.

        Historical tiers remain descriptive labels, not parallel execution gates.
        Additional SourceMethod objects and verification policies belong only to
        this invocation. Sequential configuration still honors tier order. Source
        I/O needs its own timeouts: running Python threads cannot be force-killed.
        """
        with self._state_lock:
            if self._cancel_requested:
                return AcquisitionResult(False, error='Cancelled by user', metadata=metadata)
            self._operation_stop.set()
            stop = threading.Event()
            self._operation_stop = stop
        output_file = Path(output_file)
        if output_file.exists():
            return AcquisitionResult(False, error='Output file already exists', metadata=metadata)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        sources = list(self.sources) + list(additional_sources)
        if any(not isinstance(source, SourceMethod) for source in sources):
            raise TypeError('additional_sources must contain SourceMethod objects')
        sources = [source for source in sources if source.enabled and source.name not in exclude_sources]
        if not self.config.pipeline.parallel_execution:
            priority = {'fast':0, 'medium':1, 'slow':2}
            sources.sort(key=lambda source:priority.get(source.tier,1))
        if self.cache and metadata.get('publisher'):
            try:
                sources = self._reorder_by_cache(sources, self.cache.get_best_methods(metadata['publisher'], top_n=3))
            except Exception:
                pass
        if not sources:
            return AcquisitionResult(False, error='No enabled acquisition sources', metadata=metadata)
        if progress_callback:
            label = 'Parallel sources' if self.config.pipeline.parallel_execution else 'Sequential sources'
            progress_callback(label, f'Trying {len(sources)} independent methods')
        workers = len(sources) if self.config.pipeline.parallel_execution else 1
        result = self._run_sources(sources, doi, output_file, metadata, progress_callback, workers,
                                   stop=stop, verification_policies=verification_policies)
        if not result.success and not result.error:
            result.error = 'No verified PDF acquired'
        return result

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
        workers = len(sources) if self.config.pipeline.parallel_execution else 1
        return self._run_sources(sources, doi, output_file, metadata, progress_callback, workers)

    def _execute_parallel(self, sources, doi, output_file, metadata, progress_callback=None):
        return self._run_sources(sources, doi, output_file, metadata, progress_callback, len(sources))

    def _execute_sequential(self, sources, doi, output_file, metadata, progress_callback=None):
        return self._run_sources(sources, doi, output_file, metadata, progress_callback, 1)

    def _run_sources(self, sources, doi, output_file, metadata, progress_callback, workers,
                     *, stop=None, verification_policies=None):
        """Workers own private files; the coordinator alone publishes a winner.

        Stop events are immutable across caller resets. All parallel jobs are
        submitted immediately; sequential mode submits its next job only after a
        rejection. Late I/O can finish, but its temporary candidate is discarded.
        """
        import concurrent.futures
        from collections import deque
        import os
        import tempfile

        stop = stop if stop is not None else self._operation_stop
        policies = deepcopy(verification_policies or {})
        attempts = {}
        output_file = Path(output_file)
        def cleanup(path):
            if path:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

        def attempt(source):
            from .cancellation import AcquisitionCancelled
            previous_context = current_operation_stop_event()
            _worker_context.stop = stop
            path, keep = None, False
            try:
                if stop.is_set():
                    return {'status':'cancelled', 'path':None}
                fd, name = tempfile.mkstemp(suffix='.pdf', prefix='.paperfinder-', dir=output_file.parent)
                os.close(fd)
                path = Path(name)
                record = deepcopy(metadata)
                if doi:
                    record['doi'] = doi
                override = policies.get(source.name)
                if override:
                    record['verification_policy'] = {**record.get('verification_policy', {}), **override}
                success = source.function(doi, path, deepcopy(record))
                if stop.is_set():
                    return {'status':'cancelled', 'path':None}
                if not success:
                    return {'status':'failed', 'path':None}
                if not path.exists() or not path.stat().st_size:
                    status = 'opened in browser; no PDF' if 'browser' in source.name.lower() or self._browser_opened else 'source returned no PDF'
                    return {'status':status, 'path':None}
                try:
                    verification = verify_document_identity(path, record)
                except Exception as exc:
                    verification = {'status':'unverifiable', 'reasons':[type(exc).__name__]}
                status = verification.get('status', 'unverifiable')
                if status != 'verified':
                    return {'status':status + ': ' + '; '.join(verification.get('reasons', [])), 'path':None}
                if stop.is_set():
                    return {'status':'cancelled', 'path':None}
                keep = True
                return {'status':'verified', 'path':path, 'completed_at':time.monotonic()}
            except AcquisitionCancelled:
                return {'status':'cancelled', 'path':None}
            except Exception as exc:
                return {'status':'failed: ' + type(exc).__name__, 'path':None}
            finally:
                if not keep or stop.is_set():
                    cleanup(path)
                _worker_context.stop = previous_context

        def cleanup_late(future):
            if stop.is_set() and not future.cancelled():
                try:
                    cleanup(future.result().get('path'))
                except Exception:
                    pass

        def cache_attempt(source, success):
            if self.cache and metadata.get('publisher') and metadata.get('year'):
                try:
                    self.cache.record_attempt(metadata['publisher'], metadata['year'], source.name, success)
                except Exception:
                    pass

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1,workers))
        pending, all_futures = {}, []
        queue = deque(sources)
        deadline = time.monotonic() + max(0,float(self.config.pipeline.method_timeout))
        def submit_available():
            while queue and len(pending) < workers and not stop.is_set():
                source = queue.popleft()
                future = executor.submit(attempt,source)
                future.add_done_callback(cleanup_late)
                pending[future] = source
                all_futures.append(future)
        try:
            submit_available()
            while pending and not stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                done, _ = concurrent.futures.wait(pending,timeout=min(.1,remaining),
                                                  return_when=concurrent.futures.FIRST_COMPLETED)
                # If several workers completed before this wake-up, the earliest
                # verified completion wins rather than arbitrary set iteration.
                completed = [(future,future.result()) for future in done]
                completed.sort(key=lambda pair:pair[1].get('completed_at',0))
                for future,item in completed:
                    source = pending.pop(future)
                    attempts[source.name] = item['status']
                    path = item.get('path')
                    if stop.is_set():
                        cleanup(path)
                        break
                    if item['status'] != 'verified':
                        cache_attempt(source,False)
                        continue
                    try:
                        # Cancellation and publication share a lock, so a Stop
                        # already acknowledged cannot be followed by publication.
                        with self._state_lock:
                            if stop.is_set():
                                cleanup(path)
                                break
                            os.link(path,output_file)
                            stop.set()
                    except OSError as exc:
                        attempts[source.name] = 'publish failed: ' + type(exc).__name__
                        cache_attempt(source,False)
                        continue
                    finally:
                        cleanup(path)
                    cache_attempt(source,True)
                    # Preserve failures already decided by workers finishing
                    # their cleanup. Bound this grace period independently of
                    # socket timeouts; unresponsive sources must not delay the
                    # verified winner. Their late files still clean up below.
                    if pending:
                        finished, _ = concurrent.futures.wait(pending, timeout=.05)
                        for other_future in finished:
                            other_source = pending.pop(other_future)
                            other_item = other_future.result()
                            cleanup(other_item.get('path'))
                            if other_item['status'] != 'verified':
                                attempts[other_source.name] = other_item['status']
                                cache_attempt(other_source,False)
                            else:
                                attempts[other_source.name] = 'cancelled after verified result'
                    for other in list(pending.values()) + list(queue):
                        attempts.setdefault(other.name,'cancelled after verified result')
                    if progress_callback:
                        progress_callback(source.name,'Verified PDF acquired')
                    return AcquisitionResult(True,source=source.name,filepath=output_file,
                                             metadata=metadata,attempts=attempts)
                submit_available()
            cancelled = stop.is_set()
            for source in list(pending.values()) + list(queue):
                attempts.setdefault(source.name,'cancelled' if cancelled else 'timed out')
            error = 'Cancelled by user' if cancelled else 'No verified PDF acquired'
            if any('browser' in str(value).lower() for value in attempts.values()):
                error += '; a page was opened in the browser'
            return AcquisitionResult(False,error=error,metadata=metadata,attempts=attempts)
        finally:
            stop.set()
            for future in all_futures:
                future.cancel()
                if future.done():
                    cleanup_late(future)
            executor.shutdown(wait=False,cancel_futures=True)

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
