#!/usr/bin/env python3
"""
Paper Finder - Comprehensive Academic PDF Acquisition System

System for acquiring academic papers from multiple sources.
Implements intelligent fallback strategies to maximize success rate.
"""

import sys
import time
import tempfile
import concurrent.futures
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
import random
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import yaml

# Import specialized modules
try:
    from src.acquisition.international_sources import try_fetch_from_international_sources
except ImportError:
    def try_fetch_from_international_sources(*args): return None

try:
    from src.acquisition.libgen import try_fetch_from_libgen
except ImportError:
    def try_fetch_from_libgen(*args): return None

try:
    from src.acquisition.google_scholar import try_fetch_from_google_scholar
except ImportError:
    def try_fetch_from_google_scholar(*args): return None

try:
    from src.acquisition.multilang_search import try_fetch_with_multilang
except ImportError:
    def try_fetch_with_multilang(*args): return None

try:
    from src.acquisition.deep_crawler import try_fetch_deep_crawl
except ImportError:
    def try_fetch_deep_crawl(*args): return None

try:
    from src.acquisition.chinese_crawler import try_fetch_chinese_sources
except ImportError:
    def try_fetch_chinese_sources(*args): return None

try:
    from src.acquisition.publisher_patterns import try_fetch_from_publisher_patterns
except ImportError:
    def try_fetch_from_publisher_patterns(*args): return None

# Import enhanced acquisition modules
try:
    from src.acquisition.preprints_enhanced import try_fetch_from_preprints_enhanced
except ImportError:
    try_fetch_from_preprints_enhanced = None

try:
    from src.acquisition.repositories import try_fetch_from_repositories
except ImportError:
    try_fetch_from_repositories = None

try:
    from src.acquisition.publisher_enhanced import try_fetch_publisher_enhanced
except ImportError:
    try_fetch_publisher_enhanced = None

# Import integration modules
try:
    from src.integrations.parallel_executor import execute_parallel_pipeline
except ImportError:
    execute_parallel_pipeline = None

try:
    from src.integrations.smart_cache import get_cache
except ImportError:
    get_cache = None

try:
    from src.integrations.enhanced_crossref import try_all_crossref_links, get_crossref_metadata_enhanced
except ImportError:
    try_all_crossref_links = None
    get_crossref_metadata_enhanced = None

# Import new core modules
try:
    from src.core.validation import validate_pdf
    from src.core.metadata import MetadataResolver
    from src.core.identity import IdentityResolver  # NEW: Explicit identity resolution
    from src.core.publishers import get_publisher_utils
    from src.core.config import get_config
    from src.core.pipeline import AcquisitionPipeline
except ImportError as e:
    print(f"Warning: Could not import core modules: {e}")
    validate_pdf = None
    MetadataResolver = None
    IdentityResolver = None
    get_publisher_utils = None
    get_config = None
    AcquisitionPipeline = None


# Configuration
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


@dataclass
class DownloadResult:
    """Result of a download attempt"""
    success: bool
    source: str = ""
    filepath: Optional[Path] = None
    error: str = ""
    metadata: Optional[Dict] = None
    attempts: Dict = None  # GUI expects this field
    status: str = ""
    verification: Optional[Dict] = None


class PaperFinder:
    """
    Main class for finding and downloading academic papers.
    Coordinates multiple acquisition strategies with intelligent fallback.
    """
    
    def __init__(self, silent_init: bool = False, *, config=None):
        """Initialize the paper finder"""
        # Get configuration
        if config is not None:
            self.config = config
        elif get_config:
            self.config = get_config()
        else:
            self.config = None
        
        # Create session
        self.session = self._create_session()
        
        # Initialize utilities
        if MetadataResolver:
            self.metadata_resolver = MetadataResolver(session=self.session)
        else:
            self.metadata_resolver = None
        
        # NEW: Initialize identity resolver for "identify first" philosophy
        if IdentityResolver:
            self.identity_resolver = IdentityResolver(session=self.session)
        else:
            self.identity_resolver = None
        
        if get_publisher_utils:
            self.publisher_utils = get_publisher_utils()
        else:
            self.publisher_utils = None
        
        # Construction never probes sources. Use configured domains until acquisition.
        self.scihub_domains = list(self.config.scihub.domains) if self.config else []

        # Initialize cache
        self.cache = get_cache() if get_cache and self.config and self.config.cache.enabled else None
        
        # Create pipeline (if available)
        if AcquisitionPipeline and self.config:
            self.pipeline = AcquisitionPipeline(
                config=self.config,
                metadata_resolver=self.metadata_resolver,
                cache=self.cache
            )
            # Register all sources
            self._register_sources()
        else:
            self.pipeline = None
        
        # Working domain cache
        self._working_scihub = None
        self._scihub_reachable = None
        
        # Callbacks and flags
        self._browser_callback = None
        self._cancel_requested = False
        self._browser_opened = False

    def request_cancel(self) -> None:
        """Request immediate cancellation of current search"""
        print("[CANCEL] request_cancel() called - setting _cancel_requested = True")
        self._cancel_requested = True
        if self.pipeline is not None:
            self.pipeline.request_cancel()

    def _reset_cancel(self) -> None:
        self._cancel_requested = False
        self._browser_opened = False
        if self.pipeline is not None:
            self.pipeline._reset_cancel()
    
    def _handle_book(self, isbn: str, metadata: Dict, output_dir: Path, browser_callback=None, meta_callback=None) -> DownloadResult:
        """Stage each book candidate separately and verify before publication."""
        import os
        import uuid
        from copy import deepcopy
        from src.acquisition.annas_archive import try_fetch_from_annas_archive
        from src.acquisition.libgen import try_libgen_main
        from src.core.validation import check_pdf_readable, verify_document_identity

        if meta_callback:
            try:
                meta_callback(metadata)
            except Exception:
                pass
        title, authors = metadata.get('title', ''), metadata.get('authors', [])
        safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_'))[:50].strip() or f'book_{isbn}'
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        attempts = {}
        retained = None

        def book_browser_callback(url):
            if browser_callback and not self._cancel_requested:
                browser_callback(isbn, url)

        def telegram(path):
            from src.acquisition.telegram_underground import TelegramUndergroundSource
            config = self.config.telegram
            source = TelegramUndergroundSource(session=self.session, api_id=config.api_id,
                       api_hash=config.api_hash, phone=config.phone,
                       rate_limit_per_hour=config.rate_limit_per_hour, bots=config.underground_bots)
            result = source.try_acquire(doi=isbn or title, output_file=path, metadata=deepcopy(metadata))
            return bool(result.success)

        sources = [("Anna's Archive (Book)", lambda path: try_fetch_from_annas_archive(
            doi=None, title=title, output_file=path, isbn=isbn, authors=list(authors),
            browser_callback=book_browser_callback)),
            ("LibGen Books", lambda path: try_libgen_main(title, list(authors), path))]
        telegram_config = getattr(self.config, 'telegram', None)
        if telegram_config and telegram_config.underground_enabled and telegram_config.api_id and telegram_config.api_hash:
            sources.append(("Telegram Bots (Book)", telegram))

        def discard_retained():
            if retained and retained.filepath:
                retained.filepath.unlink(missing_ok=True)

        def cancelled():
            discard_retained()
            return DownloadResult(False, error='Cancelled by user', metadata=metadata,
                                  status='cancelled', attempts=dict(attempts))

        for source_name, source in sources:
            if self._cancel_requested:
                return cancelled()
            try:
                with tempfile.TemporaryDirectory(prefix='.paperfinder-book-', dir=output_dir) as staging:
                    candidate = Path(staging) / 'candidate.pdf'
                    claimed_success = source(candidate)
                    if self._cancel_requested:
                        return cancelled()
                    if not claimed_success:
                        attempts[source_name] = 'failed'
                        continue
                    if not candidate.exists() or not candidate.stat().st_size:
                        attempts[source_name] = 'located; no downloaded PDF'
                        continue
                    try:
                        verification = verify_document_identity(candidate, metadata)
                    except Exception as exc:
                        verification = {'status': 'unverifiable', 'reasons': [type(exc).__name__]}
                    state = verification['status']
                    attempts[source_name] = state
                    if state == 'mismatch' or (state != 'verified' and not check_pdf_readable(candidate)):
                        continue
                    if self._cancel_requested:
                        return cancelled()
                    suffix = '.unverified' if state != 'verified' else ''
                    output = output_dir / f'{safe_title}{suffix}.pdf'
                    # Atomic same-filesystem publication, never overwrite a
                    # pre-existing file even if another search creates it now.
                    for collision in range(16):
                        try:
                            os.link(candidate, output)
                            break
                        except FileExistsError:
                            output = output_dir / f'{safe_title}{suffix}_{uuid.uuid4().hex[:12]}.pdf'
                    else:
                        raise FileExistsError('Could not allocate a unique output filename')
                    if self._cancel_requested:
                        output.unlink(missing_ok=True)
                        return cancelled()
                    result = DownloadResult(state == 'verified', source=source_name, filepath=output,
                                            metadata=metadata, attempts=dict(attempts), status=state,
                                            verification=verification)
                    discard_retained()
                    if state == 'verified':
                        return result
                    retained = result
            except Exception as exc:
                attempts[source_name] = 'failed: ' + type(exc).__name__
        if self._cancel_requested:
            return cancelled()
        if retained:
            retained.attempts = dict(attempts)
            return retained
        status = 'mismatch' if 'mismatch' in attempts.values() else 'not_found'
        if any(value.startswith('unverifiable') for value in attempts.values()):
            status = 'unverifiable'
        return DownloadResult(False, error='No verified book acquired', metadata=metadata,
                              status=status, attempts=attempts)

    def _handle_arxiv_direct(self, arxiv_id: str, metadata: Dict, output_dir: Path, meta_callback=None) -> DownloadResult:
        """Handle direct arXiv PDF download."""
        pdf_url = metadata.get("pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        print(f"[Fast-path] arXiv direct PDF: {pdf_url}")
        
        # Call metadata callback
        if meta_callback:
            try:
                meta_callback(metadata)
            except Exception as e:
                print(f"  Metadata callback failed: {e}")
        
        safe_id = arxiv_id.replace('/', '_').replace('\\', '_')
        output_file = output_dir / f"arxiv_{safe_id}.pdf"
        
        try:
            resp = self.session.get(pdf_url, timeout=30, stream=True)
            if resp.status_code == 200 and resp.headers.get('content-type', '').lower().startswith('application/pdf'):
                with output_file.open('wb') as f:
                    for chunk in resp.iter_content(chunk_size=1024*1024):
                        if chunk:
                            f.write(chunk)
                
                # Basic PDF validation
                if validate_pdf is not None and validate_pdf(output_file):
                    print("✓ Success via arXiv direct PDF")
                    return DownloadResult(
                        success=True,
                        source="arXiv Direct",
                        filepath=output_file,
                        metadata=metadata,
                        attempts={"arXiv Direct": "success"}
                    )
                else:
                    output_file.unlink(missing_ok=True)
        except Exception as e:
            print(f"  arXiv direct download failed: {type(e).__name__}")
        
        # Fall through to standard pipeline
        return DownloadResult(success=False, error="arXiv direct download failed")
    
    def _handle_biorxiv_direct(self, doi: str, metadata: Dict, output_dir: Path, meta_callback=None) -> DownloadResult:
        """Handle direct bioRxiv/medRxiv PDF download."""
        print(f"[Fast-path] bioRxiv/medRxiv direct access for DOI: {doi}")
        
        # Call metadata callback
        if meta_callback:
            try:
                meta_callback(metadata)
            except Exception as e:
                print(f"  Metadata callback failed: {e}")
        
        safe_doi = doi.replace('/', '_').replace('\\', '_')
        output_file = output_dir / f"{safe_doi}.pdf"
        
        # Try both bioRxiv and medRxiv
        for server in ["biorxiv", "medrxiv"]:
            try:
                # Try PDF URL first
                pdf_url = f"https://www.{server}.org/content/{doi}.full.pdf"
                print(f"  Trying {server} PDF: {pdf_url}")
                resp = self.session.get(pdf_url, timeout=30, stream=True)
                
                if resp.status_code == 200:
                    content_type = resp.headers.get('content-type', '').lower()
                    if 'pdf' in content_type or resp.content[:4] == b'%PDF':
                        with output_file.open('wb') as f:
                            for chunk in resp.iter_content(chunk_size=1024*1024):
                                if chunk:
                                    f.write(chunk)
                        
                        if validate_pdf and validate_pdf(output_file):
                            print(f"✓ Success via {server} direct PDF")
                            return DownloadResult(
                                success=True,
                                source=f"{server.title()} Direct",
                                filepath=output_file,
                                metadata=metadata,
                                attempts={f"{server} Direct": "success"}
                            )
                        else:
                            output_file.unlink(missing_ok=True)
                    else:
                        # Not a PDF, try HTML landing page
                        html_url = f"https://www.{server}.org/content/{doi}"
                        print(f"  PDF not available, trying {server} HTML: {html_url}")
                        if self._browser_callback:
                            self._browser_callback(html_url)
                            self._browser_opened = True
                            return DownloadResult(
                                success=True,
                                source=f"{server.title()} (Browser)",
                                filepath=None,
                                metadata=metadata,
                                attempts={f"{server} Browser": "opened in browser"}
                            )
            except Exception as e:
                print(f"  {server} direct access failed: {type(e).__name__}")
                continue
        
        # Fall through if both fail
        return DownloadResult(success=False, error="bioRxiv/medRxiv direct download failed")
    
    def _check_cancel(self) -> bool:
        """Check if cancellation was requested. Returns True if cancelled."""
        from src.core.pipeline import operation_cancelled
        return self._cancel_requested or operation_cancelled()
    
    def _register_sources(self) -> None:
        """Register all acquisition sources with the pipeline.
        
        Sources are strictly tiered according to README:
        - FAST: Shadow libraries & direct URLs (<20s typical)
        - MEDIUM: OA repositories & APIs (<60s typical)
        - SLOW: Web discovery & deep search (<120s max)
        """
        if not self.pipeline:
            return
        
        # ==================== FAST TIER ====================
        # Shadow libraries (highest priority per README)
        self.pipeline.register_source("SciHub", self._try_scihub, tier='fast')
        self.pipeline.register_source("Anna's Archive", self._try_annas_archive, tier='fast')
        self.pipeline.register_source("LibGen", self._try_libgen, tier='fast')
        
        # Telegram bots (runs in parallel with shadow libraries)
        if self.config and hasattr(self.config, 'telegram'):
            if self.config.telegram.underground_enabled and self.config.telegram.api_id and self.config.telegram.api_hash:
                self.pipeline.register_source("Telegram Bots", self._try_telegram_underground, tier='fast')
        
        # Direct fast-paths (arXiv, bioRxiv, medRxiv handled in find())
        # Browser-based OA (immediate response)
        self.pipeline.register_source("Open Access (Browser)", self._try_browser_download, tier='fast')
        
        # ==================== MEDIUM TIER ====================
        # Open Access APIs and repositories
        
        self.pipeline.register_source("Unpaywall", self._try_unpaywall, tier='medium')
        self.pipeline.register_source("PubMed Central", self._try_pmc, tier='medium')
        self.pipeline.register_source("Europe PMC", self._try_europepmc, tier='medium')
        self.pipeline.register_source("Semantic Scholar", self._try_semantic_scholar, tier='medium')
        self.pipeline.register_source("CORE.ac.uk", self._try_core, tier='medium')
        self.pipeline.register_source("Open Repositories", self._try_repositories, tier='medium')
        self.pipeline.register_source("Crossref Direct", self._try_crossref_links, tier='medium')
        
        # Publisher landing pages
        self.pipeline.register_source("Landing Page", self._try_landing_page_extraction, tier='medium')
        self.pipeline.register_source("Advanced Bypass", self._try_advanced_bypass, tier='medium')
        self.pipeline.register_source("Publisher Patterns", self._try_publisher_patterns, tier='medium')
        
        # Preprints (if not handled by fast-path)
        self.pipeline.register_source("Preprints Enhanced", self._try_preprints, tier='medium')
        
        # ==================== SLOW TIER ====================
        # Web discovery and deep search
        self.pipeline.register_source("Google Scholar", self._try_google_scholar, tier='slow')
        self.pipeline.register_source("International", self._try_international, tier='slow')
        self.pipeline.register_source("Multi-language", self._try_multilang, tier='slow')
        self.pipeline.register_source("Chinese Sources", self._try_chinese, tier='slow')
        self.pipeline.register_source("Deep Crawl", self._try_deep_crawl, tier='slow')
        
        # Dynamic discovery of modular sources in src/acquisition/
        # This will auto-register any SimpleAcquisitionSource subclasses
        self._register_dynamic_sources()
    
    def _register_dynamic_sources(self) -> None:
        """Dynamically discover and register modular acquisition sources."""
        if not self.pipeline:
            return

        try:
            import pkgutil
            import importlib
            import inspect
            from src.core.base_source import SimpleAcquisitionSource
        except ImportError:
            # Core modules not available; skip dynamic discovery
            return

        # Avoid duplicates: don't register sources that are already present
        try:
            existing = set(self.pipeline.get_registered_sources())
        except Exception:
            existing = set()

        try:
            import src.acquisition as acquisition_pkg
        except ImportError:
            return

        for module_info in pkgutil.iter_modules(acquisition_pkg.__path__, acquisition_pkg.__name__ + "."):
            module_name = module_info.name
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue

            for _, obj in inspect.getmembers(module, inspect.isclass):
                # Only consider SimpleAcquisitionSource subclasses
                if not issubclass(obj, SimpleAcquisitionSource) or obj is SimpleAcquisitionSource:
                    continue

                # Disabled messaging integrations must not be reactivated by
                # dynamic discovery or environment credentials.
                if obj.__name__ == 'TelegramUndergroundSource':
                    telegram_config = getattr(self.config, 'telegram', None)
                    if not (telegram_config and telegram_config.underground_enabled
                            and telegram_config.api_id and telegram_config.api_hash):
                        continue
                # Instantiate once to read metadata such as name
                try:
                    # Special handling for TelegramUndergroundSource - pass config
                    if obj.__name__ == 'TelegramUndergroundSource' and self.config and hasattr(self.config, 'telegram'):
                        instance = obj(
                            session=self.session,
                            api_id=self.config.telegram.api_id,
                            api_hash=self.config.telegram.api_hash,
                            phone=self.config.telegram.phone,
                            rate_limit_per_hour=self.config.telegram.rate_limit_per_hour,
                            bots=self.config.telegram.underground_bots
                        )
                    else:
                        instance = obj(session=self.session)
                    source_name = getattr(instance, "name", None)
                except Exception:
                    continue

                if not source_name or source_name in existing:
                    continue

                tier = getattr(obj, "tier", "medium")

                def make_wrapper(source_cls, config=self.config):
                    def wrapper(doi, output_file, meta, _cls=source_cls, _session=self.session, _config=config):
                        try:
                            # Special handling for TelegramUndergroundSource
                            if _cls.__name__ == 'TelegramUndergroundSource' and _config and hasattr(_config, 'telegram'):
                                src = _cls(
                                    session=_session,
                                    api_id=_config.telegram.api_id,
                                    api_hash=_config.telegram.api_hash,
                                    phone=_config.telegram.phone,
                                    rate_limit_per_hour=_config.telegram.rate_limit_per_hour,
                                    bots=_config.telegram.underground_bots
                                )
                            else:
                                src = _cls(session=_session)
                            result = src.try_acquire(doi, output_file, meta)
                            return bool(result and result.success)
                        except Exception:
                            return False
                    return wrapper

                self.pipeline.register_source(source_name, make_wrapper(obj), tier=tier)
                existing.add(source_name)
    
    def _create_session(self) -> requests.Session:
        """Create HTTP session with proper headers"""
        from src.core.cancellation import CancellableSession
        session = CancellableSession()
        session.headers.update({"User-Agent": UA})
        return session

    def _get(self, url: str, *, timeout: int = 15, max_retries: int = 3, **kwargs) -> requests.Response:
        """HTTP GET with retry/backoff for network failures.

        Keeps behavior simple but avoids failing immediately on transient network issues.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.get(url, timeout=timeout, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                # On last attempt, raise; otherwise brief backoff
                if attempt == max_retries:
                    raise
                from src.core.cancellation import cancellable_sleep
                cancellable_sleep(1.0 * attempt)
        # Should not reach here
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("HTTP request failed without explicit exception")

    # ------------------------------------------------------------------
    # Reference resolution helpers
    # ------------------------------------------------------------------
    def _extract_doi_from_text(self, text: str) -> Optional[str]:
        """Try to pull a DOI out of an arbitrary reference string.

        Handles patterns like:
        - "DOI: 10.1021/jacs.3c00908"
        - "https://doi.org/10.1021/jacs.3c00908"
        - "... 10.1021/jacs.3c00908)" etc.
        """
        if not text:
            return None

        # Normalize whitespace and strip trailing backticks/quotes
        s = " ".join(text.strip().split())
        s = s.rstrip("`'\"")

        m = re.search(r"https?://(?:www\.)?nature\.com/articles/([A-Za-z0-9.\-]+)", s, flags=re.IGNORECASE)
        if m:
            code = m.group(1)
            doi = f"10.1038/{code}"
            return doi

        # First, look for bare DOI pattern
        m = re.search(r"10\.\d{4,9}/\S+", s)
        if m:
            # Strip trailing punctuation that often clings to DOIs (including backticks)
            doi = m.group(0).rstrip(").,;\"]\'\'`")
            return doi

        # Next, handle explicit "DOI:" prefix, in case regex above fails
        m = re.search(r"doi\s*[:=]\s*(10\.\d{4,9}/\S+)", s, flags=re.IGNORECASE)
        if m:
            doi = m.group(1).rstrip(").,;\"]\'`")
            return doi

        # Finally, handle doi.org URLs
        m = re.search(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/\S+)", s, flags=re.IGNORECASE)
        if m:
            doi = m.group(1).rstrip(").,;\"]\'`")
            return doi

        return None

    def _normalize_doi(self, doi: str) -> str:
        """Normalize a DOI by stripping common supplementary/SI suffixes.
        
        Many publishers (especially ACS) use patterns like:
        - 10.1021/jacs.3c00908.s001 (supplementary info)
        
        We want to normalize these to the main article DOI.
        """
        if not doi:
            return doi
            
        # ACS and similar: strip .s### suffix
        # Pattern: match everything up to .s### at the end
        m = re.match(r"(.+)\.s\d+$", doi, flags=re.IGNORECASE)
        if m:
            normalized = m.group(1)
            print(f"  Normalized SI DOI {doi} → {normalized}")
            return normalized
            
        return doi
    
    def _normalize_reference_for_crossref(self, ref: str) -> str:
        """Normalize messy reference strings before sending to Crossref.

        This especially helps when titles are pasted without spaces, e.g.:
        "DynamicEnvironmentalConditionsAffecttheCompositionofa ModelPrebioticReactionNetwork".

        Strategy:
        1. Keep whitespace as-is between tokens.
        2. For very long tokens that contain lowercase+Uppercase patterns,
           insert spaces before capitals (simple camel-case splitting).
        """
        if not ref:
            return ref

        tokens = ref.split()
        new_tokens = []
        for tok in tokens:
            # Only try to split obviously crushed tokens
            if len(tok) > 25 and re.search(r"[a-z][A-Z]", tok):
                # Insert space before capital letters that follow lowercase letters
                split_tok = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", tok)
                new_tokens.append(split_tok)
            else:
                new_tokens.append(tok)

        return " ".join(new_tokens)
    
    def _resolve_via_crossref(self, ref: str) -> Optional[str]:
        """Compatibility entry point using the shared multi-index matching policy."""
        from src.core.discovery import DiscoveryService
        result = DiscoveryService(session=self.session).search(ref, mode="identify")
        selected = result.get("selected")
        return selected.get("doi") if result["status"] == "matched" and selected else None

    def resolve_reference(self, ref: str) -> Optional[str]:
        return self._resolve_via_crossref(ref)

    def acquire(self, doi_or_ref: str, output_dir: Optional[Path] = None, oa_callback=None, meta_callback=None, browser_callback=None) -> DownloadResult:
        """Alias for find() - for compatibility with test harness and other code."""
        return self.find(doi_or_ref, output_dir, oa_callback, meta_callback, browser_callback)

    def find(self, ref: str, output_dir: Optional[Path] = None, oa_callback=None, meta_callback=None, browser_callback=None, *, recent_sources=False, contact_email=None) -> DownloadResult:
        """Resolve an identity before allowing any acquisition source to run."""
        self._reset_cancel()
        if not self.identity_resolver:
            return DownloadResult(False, error="Identity resolver is unavailable", status="unavailable")
        record = self.identity_resolver.resolve(ref)
        status = record.get("status", "")
        identifier = record.get("identifier") or {}
        if status in {"ambiguous", "not_found", "unavailable"} or record.get("error"):
            return DownloadResult(False, error=record.get("error") or "Select a candidate before downloading",
                                  metadata=record, status=status or "not_found", attempts={})
        if not identifier.get("value"):
            return DownloadResult(False, error="Could not identify the requested work", metadata=record,
                                  status="not_found", attempts={})
        if self._cancel_requested:
            return DownloadResult(False, error="Cancelled by user", status="cancelled", metadata=record)
        return self.find_record(record, output_dir, oa_callback=oa_callback, meta_callback=meta_callback,
                                browser_callback=browser_callback, _continue_operation=True,
                                recent_sources=recent_sources, contact_email=contact_email)

    def find_record(self, record: Dict, output_dir: Optional[Path] = None, oa_callback=None,
                    meta_callback=None, browser_callback=None, _continue_operation=False, recent_sources=False, contact_email=None) -> DownloadResult:
        """Acquire a selected canonical record without repeating or changing its identity."""
        from copy import deepcopy
        record = deepcopy(record)
        record.pop("fulltext_location", None)
        identifier = record.get("identifier") or {}
        kind, value = identifier.get("type"), identifier.get("value")
        if not value:
            return DownloadResult(False, error="The selected record has no identifier", metadata=record, status="not_found")
        if not _continue_operation:
            self._reset_cancel()
        if self._cancel_requested:
            return DownloadResult(False, error="Cancelled by user", status="cancelled", metadata=record)
        output_dir = Path(output_dir or Path.cwd())
        output_dir.mkdir(parents=True, exist_ok=True)
        if meta_callback:
            meta_callback(record)
        links = []
        if isinstance(record.get("url"), str) and record["url"].startswith(("https://", "http://")):
            links.append(record["url"])
        def capture_link(*args):
            url = args[-1] if args else None
            if isinstance(url, str) and url.startswith(("https://", "http://")) and url not in links:
                links.append(url)
                callback = browser_callback or oa_callback
                if callback:
                    callback(value, url)
        self._browser_callback = capture_link
        result = None
        version_selection_required = False
        if kind == "isbn":
            result = self._handle_book(value, record, output_dir, capture_link, meta_callback)
        elif self.pipeline is not None:
            from src.acquisition.racing import acquire_record_race
            result = acquire_record_race(self, record, output_dir,
                recent_sources=recent_sources, contact_email=contact_email)
            record = result.metadata
            for location in record.get("access_options", {}).get("locations", []):
                capture_link(location.get("landing_page_url") or location.get("url"))
        else:
            urls = list(record.get("pdf_urls") or [])
            if record.get("pdf_url"):
                urls.insert(0, record["pdf_url"])
            if kind == "arxiv":
                urls.append(f"https://arxiv.org/pdf/{value}")
            elif kind in {"biorxiv", "medrxiv"}:
                urls.append(f"https://www.{kind}.org/content/{value}.full.pdf")
            doi = record.get("doi") or (value if kind in {"doi", "biorxiv", "medrxiv"} else None)
            if urls and not (recent_sources and doi and kind == "doi"):
                result = self._download_record_urls(record, urls, output_dir)
            if recent_sources and doi and (result is None or not result.success) and not self._cancel_requested:
                try:
                    access = self.find_access_options(record, contact_email=contact_email)
                except Exception:
                    access = {"status": "unavailable", "locations": [], "alternatives": [],
                              "errors": {"discovery": {"kind": "error", "message": "Full-text discovery failed"}}}
                # Preserve known preprint/conflict evidence even if today's
                # provider lookup fails or the selected metadata was cached.
                from src.acquisition.recent_open_access import _location
                for indexed in record.get("indexed_locations", []):
                    if not indexed.get("requires_selection"):
                        continue
                    alternative = _location(indexed.get("source") or "indexed", doi,
                        pdf=indexed.get("pdf_url"), landing=indexed.get("landing_page_url"),
                        version=indexed.get("version"), license=indexed.get("license"))
                    if alternative:
                        alternative["requires_selection"] = True
                        if indexed.get("version_conflict"):
                            alternative["version"] = "conflicting"
                        existing = access.setdefault("alternatives", [])
                        if not any(item.get("url") == alternative["url"] for item in existing):
                            existing.append(alternative)
                record["access_options"] = access
                version_selection_required = bool(access.get("alternatives"))
                # A repository may advertise an HTML article before a PDF URL.
                # Bound this extra work and never promote a preprint implicitly.
                from src.acquisition.recent_open_access import discover_landing_pdf
                landing_deadline = time.monotonic() + 15
                landing_checks = 0
                for index, location in enumerate(access.get("locations", [])):
                    if self._cancel_requested or landing_checks >= 3 or time.monotonic() >= landing_deadline:
                        break
                    if (location.get("downloadable") or location.get("availability") != "open"
                            or location.get("requires_selection") or location.get("version") == "submittedVersion"):
                        continue
                    landing_checks += 1
                    try:
                        expanded = discover_landing_pdf(location, session=self.session,
                            timeout=min(5, max(.1, landing_deadline - time.monotonic())))
                    except Exception:
                        access.setdefault("errors", {})[f"landing_{index}"] = {
                            "kind": "error", "message": "Repository landing-page inspection failed."}
                        continue
                    if expanded:
                        access["locations"][index] = expanded
                locations = [location for location in access.get("locations", [])
                             if location.get("downloadable") and location.get("pdf_url")
                             and not location.get("requires_selection") and location.get("version") != "submittedVersion"]
                record["fulltext_locations"] = locations
                for location in access.get("locations", []):
                    capture_link(location.get("landing_page_url") or location.get("url"))
                blocked_urls = {location.get("pdf_url") for group in ("alternatives", "embargoed", "closed")
                                for location in access.get(group, [])}
                eligible_urls = [location["pdf_url"] for location in locations]
                # Once a preprint/version conflict is known, only explicitly
                # classified main-article locations may be downloaded here.
                if not version_selection_required:
                    eligible_urls.extend(url for url in urls if url not in blocked_urls)
                new_urls = list(dict.fromkeys(eligible_urls))
                if new_urls and not self._cancel_requested:
                    recent = self._download_record_urls(record, new_urls, output_dir)
                    attempts = {**(result.attempts or {} if result else {}), **(recent.attempts or {})}
                    if recent.success and result and result.filepath and result.filepath != recent.filepath:
                        try:
                            Path(result.filepath).unlink(missing_ok=True)
                        except OSError:
                            attempts["review_copy_cleanup"] = "Could not remove superseded review copy"
                    if recent.success or recent.status == "cancelled" or result is None or not result.filepath:
                        result = recent
                    result.attempts = attempts
                    if recent.success:
                        for location in locations:
                            if recent.attempts.get(location["pdf_url"]) == "verified":
                                record["fulltext_location"] = location
                                break
            if (result is None or not result.success) and doi and not self._cancel_requested:
                if version_selection_required:
                    # Continue independent sources, but require the requested
                    # identifier before an unclassified legacy copy can win.
                    record["verification_policy"] = {"require_identifier": True}
                output_file = self._available_output(output_dir, doi)
                fallback = self._execute_pipeline(doi, output_file, meta_callback=None,
                                                  oa_callback=capture_link, metadata=record,
                                                  exclude_sources=("Unpaywall", "Europe PMC", "Open Access (Browser)") if recent_sources else ())
                fallback = self._verify_result(fallback, record)
                attempts = {**(result.attempts or {} if result else {}), **(fallback.attempts or {})}
                # Remove only the review copy created by this operation, after a
                # verified replacement exists. Keep evidence from every source.
                if fallback.success and result and result.filepath and result.filepath != fallback.filepath:
                    try:
                        Path(result.filepath).unlink(missing_ok=True)
                    except OSError:
                        attempts["review_copy_cleanup"] = "Could not remove superseded review copy"
                if fallback.success or fallback.status == "cancelled" or result is None or not result.filepath:
                    result = fallback
                result.attempts = attempts
        if self._cancel_requested:
            return DownloadResult(False, error="Cancelled by user", metadata=record,
                                  status="cancelled", attempts=result.attempts if result else {})
        if result is None:
            message = ("Preprint or conflicting-version alternatives found; inspect and choose a copy before downloading."
                       if version_selection_required else "No downloadable full-text location found")
            result = DownloadResult(False, error=message, metadata=record, status="located" if version_selection_required else "not_found")
        final = self._verify_result(result, record)
        if links:
            final.metadata["links"] = links
            if not final.success and not final.filepath and final.status not in {"cancelled", "mismatch", "unverifiable"}:
                final.status = "located"
                final.error = "Article links found; full-text download has not been verified"
        return final

    def find_access_options(self, record, contact_email=None):
        """Inspect fresh full-text locations without downloading or opening pages."""
        from src.acquisition.access_options import discover_access_options
        identifier = record.get("identifier") or {}
        doi = record.get("doi") or (identifier.get("value") if identifier.get("type") == "doi" else None)
        if not doi:
            return {"status": "not_found", "locations": [], "alternatives": [],
                    "errors": {"identity": {"kind": "missing_doi", "message": "Full-text copy lookup needs a DOI"}}}
        if not contact_email:
            contact_email = getattr(getattr(self.config, "api", None), "unpaywall_email", None)
        return discover_access_options(record, session=self.session, email=contact_email)

    @staticmethod
    def _available_output(directory: Path, identifier: str) -> Path:
        """Preserve an existing download instead of overwriting it."""
        import uuid
        name = re.sub(r'[^\w.\-]', '_', identifier)[:150] or "paper"
        output = directory / f"{name}.pdf"
        if output.exists():
            output = directory / f"{name}_{uuid.uuid4().hex[:8]}.pdf"
        return output

    def _download_record_urls(self, record: Dict, urls: List[str], directory: Path, *, session=None) -> DownloadResult:
        """Try provider-discovered PDF locations with bounded size and atomic publication."""
        import os
        import time
        from urllib.parse import urlparse
        from src.core.validation import verify_document_identity
        limit = int(getattr(self.config.validation, "max_size_mb", 100)) * 1024 * 1024
        attempts = {}
        retained = None
        deadline = time.monotonic() + 45
        for url in list(dict.fromkeys(urls))[:5]:
            if time.monotonic() >= deadline:
                attempts["deadline"] = "Direct download budget exhausted"
                break
            parsed = urlparse(url)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
                continue
            if self._check_cancel():
                return DownloadResult(False, error="Cancelled by user", status="cancelled", attempts=attempts)
            fd, name = tempfile.mkstemp(prefix=".paperfinder-", suffix=".pdf", dir=directory)
            os.close(fd)
            temporary = Path(name)
            response = None
            try:
                remaining = max(.1, deadline - time.monotonic())
                response = (session or self.session).get(url, stream=True, timeout=(min(5, remaining), min(15, remaining)))
                if response.status_code != 200:
                    attempts[url] = f"HTTP {response.status_code}"
                    continue
                length = response.headers.get("Content-Length")
                if length and int(length) > limit:
                    attempts[url] = "File exceeds size limit"
                    continue
                size = 0
                with temporary.open('wb') as target:
                    for chunk in response.iter_content(chunk_size=65536):
                        if self._check_cancel():
                            raise InterruptedError("Cancelled by user")
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Download deadline exceeded")
                        size += len(chunk)
                        if size > limit:
                            raise ValueError("File exceeds size limit")
                        target.write(chunk)
                if self._check_cancel():
                    raise InterruptedError("Cancelled by user")
                verification = verify_document_identity(temporary, record)
                state = verification["status"]
                attempts[url] = state
                if state == "mismatch":
                    continue
                if state == "unverifiable" and temporary.read_bytes()[:5] != b'%PDF-':
                    continue
                output = self._available_output(directory, record['identifier']['value'])
                if state == "unverifiable":
                    output = self._available_output(directory, output.stem + ".unverified")
                if self._check_cancel():
                    raise InterruptedError("Cancelled by user")
                for retry in range(5):
                    try:
                        os.link(temporary, output)
                        break
                    except FileExistsError:
                        output = self._available_output(directory, output.stem)
                else:
                    raise FileExistsError("Could not reserve a unique output filename")
                temporary.unlink()
                result = DownloadResult(state == "verified", source="Discovered full text", filepath=output,
                                        metadata=record, attempts=dict(attempts), status=state, verification=verification)
                if state == "verified":
                    if retained and retained.filepath:
                        retained.filepath.unlink(missing_ok=True)
                    return result
                if retained and retained.filepath:
                    retained.filepath.unlink(missing_ok=True)
                retained = result
            except InterruptedError:
                return DownloadResult(False, error="Cancelled by user", status="cancelled", attempts=attempts)
            except (requests.RequestException, OSError, ValueError, TimeoutError) as exc:
                attempts[url] = type(exc).__name__
            finally:
                if response is not None:
                    response.close()
                temporary.unlink(missing_ok=True)
        if self._check_cancel():
            return DownloadResult(False, error="Cancelled by user", status="cancelled", attempts=attempts)
        return retained or DownloadResult(False, error="Discovered full-text locations did not yield a verified paper",
                                          metadata=record, attempts=attempts, status="not_found")

    @staticmethod
    def _verify_result(result, record: Dict) -> DownloadResult:
        from src.core.validation import verify_document_identity
        filepath = getattr(result, "filepath", None)
        status = getattr(result, "status", "") or "not_found"
        verification = getattr(result, "verification", None)
        error = result.error or ""
        attempts = result.attempts or {}
        if error == "Cancelled by user":
            status = "cancelled"
        elif any(str(v).startswith("unverifiable") for v in attempts.values()):
            status = "unverifiable"
        elif any(str(v).startswith("mismatch") for v in attempts.values()):
            status = "mismatch"
        success = False
        if filepath:
            verification = verify_document_identity(Path(filepath), record)
            status = verification["status"]
            success = status == "verified"
            if success:
                error = ""
            if not success:
                error = "; ".join(verification.get("reasons", [])) or "Document identity could not be verified"
        elif result.success:
            status = "located"
            verification = {"status": "unverifiable", "reasons": ["No local document was verified"]}
            error = "Article located; downloaded full text has not been verified"
        return DownloadResult(success, source=result.source, filepath=filepath, error=error,
                              metadata=record, attempts=result.attempts or {}, status=status,
                              verification=verification)

    def _execute_pipeline(self, doi: str, output_file: Path, meta_callback=None, oa_callback=None, metadata=None, exclude_sources=()) -> DownloadResult:
        """Execute the multi-source acquisition pipeline"""
        import time
        start_time = time.time()
        
        print(f"Searching for: {doi}")
        
        if metadata is not None:
            meta = dict(metadata)
            meta.setdefault("doi", doi)
        else:
            # Gather metadata - use new metadata resolver if available
            print("Gathering metadata...")
            try:
                if self.metadata_resolver:
                    meta = self.metadata_resolver.get_crossref_metadata(doi)
                    if not meta:
                        meta = self._get_metadata(doi)
                elif get_crossref_metadata_enhanced:
                    meta = get_crossref_metadata_enhanced(doi)
                    if not meta:
                        meta = self._get_metadata(doi)
                else:
                    meta = self._get_metadata(doi)
            except Exception as e:
                print(f"  Metadata lookup failed: {e}")
                meta = {"doi": doi}
        
        if meta.get("title"):
            print(f"Found paper: {meta['title']}")
            if meta.get("year"):
                print(f"Year: {meta['year']}")
            if meta.get("journal"):
                print(f"Journal: {meta['journal']}")
            if meta.get("publisher"):
                print(f"Publisher: {meta['publisher']}")
        
        # Metadata callback (for GUI)
        if meta_callback is not None:
            try:
                meta_callback(meta)
            except Exception as e:
                print(f"  Metadata callback failed: {e}")

        # Early cancellation check
        if self._cancel_requested:
            total_time = time.time() - start_time
            print(f"\n✗ Search cancelled by user (total: {total_time:.1f}s)")
            return DownloadResult(
                success=False,
                error="Cancelled by user",
                metadata=meta,
                attempts={}
            )

        # Use new pipeline if available, otherwise fall back to old implementation
        if self.pipeline:
            # FIX 1: STOP ON OA SUCCESS - Share cancel and browser flags with pipeline
            self.pipeline._cancel_requested = self._cancel_requested
            self.pipeline._browser_opened = self._browser_opened
            
            # Execute pipeline
            print("\n[Using new pipeline with parallel execution]")
            result = self.pipeline.execute(doi, output_file, meta, exclude_sources=exclude_sources)
            
            # FIX 1: Update our flags from pipeline and check for browser success
            self._cancel_requested = self.pipeline._cancel_requested
            self._browser_opened = self.pipeline._browser_opened
            
            return result
        
        # FALLBACK: Old inline implementation if pipeline not available
        print("\n[Pipeline not available - using fallback implementation]")
        
        # Track attempts
        attempts: Dict[str, str] = {}
        
        # Try acquisition methods in order
        # STRATEGY: Sci-Hub First → OA/Shadow Libraries → Preprints/Author Versions → Repositories → Publisher Tricks → Deep Web Search
        methods = [
            ("SciHub", self._try_scihub),  # PRIORITIZE: Most reliable for paywalled papers
            ("Open Access (Browser)", self._try_browser_download),
            ("Anna's Archive", self._try_annas_archive),  # 100M+ books/papers - BEST for book chapters!
            ("LibGen", self._try_libgen),
            ("Preprints & Author Versions", self._try_preprints),  # NEW ENHANCED: arXiv, bioRxiv, medRxiv, chemRxiv, SSRN, OSF, Europe PMC, HAL, CORE
            ("Open Repositories", self._try_repositories),  # NEW: Zenodo, Figshare, OSF Storage, Institutional Repos, Dataverse
            ("Publisher-Specific Tricks", self._try_springer_enhanced),  # NEW ENHANCED: Nature, Science, Elsevier, Wiley, IEEE, ACS + legacy
            ("Crossref Direct", self._try_crossref_links),
            ("Semantic Scholar", self._try_semantic_scholar),
            ("PubMed Central", self._try_pmc),
            ("Landing Page", self._try_landing_page_extraction),
            ("Advanced Bypass", self._try_advanced_bypass),
            ("International", self._try_international),
            ("Google Scholar", self._try_google_scholar),
            ("Multi-language", self._try_multilang),
            ("Chinese Sources", self._try_chinese),
            ("Deep Crawl", self._try_deep_crawl),
        ]
        
        # Add Telegram bots to fast methods if enabled
        if self.config and hasattr(self.config, 'telegram') and self.config.telegram.underground_enabled and self.config.telegram.api_id and self.config.telegram.api_hash:
            methods.insert(4, ("Telegram Bots", self._try_telegram_underground))
        
        excluded = set(exclude_sources)
        if "Preprints Enhanced" in excluded:
            excluded.add("Preprints & Author Versions")
        methods = [method for method in methods if method[0] not in excluded]

        # Reorder methods based on cache if available
        if self.cache and meta.get("publisher") and meta.get("year"):
            methods = self.cache.reorder_methods(methods, meta.get("publisher"), meta.get("year"))
            print(f"Methods reordered based on historical success for {meta.get('publisher')}")
        
        # Group methods for parallel execution
        # Group 1: Fast sources (usually succeed quickly or fail fast) - SciHub prioritized
        # MOVED: 'Open Access (Browser)' moved to Medium to allow Sci-Hub to win first
        fast_methods = [m for m in methods if m[0] in ["SciHub", "Anna's Archive", "LibGen", "Telegram Bots", "Preprints & Author Versions", "Publisher-Specific Tricks"]]
        # Group 2: Medium sources (API-based, moderate speed)
        medium_methods = [m for m in methods if m[0] in ["Open Access (Browser)", "Open Repositories", "Crossref Direct", "Semantic Scholar", "PubMed Central", "Landing Page", "Advanced Bypass"]]
        # Group 3: Slow sources (web scraping, deep search)
        slow_methods = [m for m in methods if m[0] in ["International", "Google Scholar", "Multi-language", "Chinese Sources", "Deep Crawl"]]
        
        # Try parallel execution (always enabled - follow README philosophy)
        print("\n[Using parallel execution for faster search]")
        
        method_groups = []
        if fast_methods:
            method_groups.append(("Fast Sources", fast_methods))
        if medium_methods:
            method_groups.append(("Medium Sources", medium_methods))
        if slow_methods:
            method_groups.append(("Deep Sources", slow_methods))
        
        # Execute groups in parallel
        for group_name, group_methods in method_groups:
            print(f"\n[{group_name}] - Running {len(group_methods)} methods in parallel...")
            elapsed = time.time() - start_time
            print(f"  [{elapsed:.1f}s elapsed]")
            
            # Create wrapper functions that handle caching
            def make_wrapper(method_name, method_func):
                def wrapper():
                    # Check cancellation BEFORE doing any work
                    if self._cancel_requested:
                        return False
                    try:
                        method_start = time.time()
                        success = method_func(doi, output_file, meta)
                        method_time = time.time() - method_start
                        
                        # Record in cache only if not cancelled
                        if not self._cancel_requested and cache and meta.get("publisher") and meta.get("year"):
                            cache.record_attempt(meta.get("publisher"), meta.get("year"), method_name, success)
                        
                        if success and not self._cancel_requested:
                            print(f"  ✓ {method_name} succeeded in {method_time:.1f}s")
                        
                        return success
                    except Exception as e:
                        if not self._cancel_requested:
                            if cache and meta.get("publisher") and meta.get("year"):
                                cache.record_attempt(meta.get("publisher"), meta.get("year"), method_name, False)
                            print(f"  ✗ {method_name} failed: {type(e).__name__}")
                        return False
                return wrapper
            
            # Wrap methods
            wrapped_methods = [(name, make_wrapper(name, func)) for name, func in group_methods]
            
            # Execute in parallel
            import concurrent.futures
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
            try:
                future_to_method = {executor.submit(func): name for name, func in wrapped_methods}

                # Wait for first success or all to complete (max 60s per group),
                # but wake up frequently so we can react quickly to cancellation.
                group_start = time.time()

                while future_to_method:
                    # Check for user cancellation frequently (Stop button)
                    if self._cancel_requested:
                        print("  ⚠ STOP clicked - cancelling all running methods immediately (non-blocking)")
                        for f in future_to_method:
                            f.cancel()
                        total_time = time.time() - start_time
                        print(f"\n✗ Search cancelled by user (total: {total_time:.1f}s)")
                        return DownloadResult(
                            success=False,
                            error="Cancelled by user",
                            metadata=meta,
                            attempts=attempts,
                        )
                    
                    # Check if browser was opened - if so, stop searching!
                    if self._browser_opened:
                        print("  ✓ Browser opened - stopping parallel search")
                        for f in future_to_method:
                            f.cancel()
                        total_time = time.time() - start_time
                        meta["is_oa"] = True
                        print(f"\n✓ Success - Paper opened in browser (total: {total_time:.1f}s)")
                        return DownloadResult(
                            success=True,
                            source="Open Access (Browser)",
                            filepath=None,
                            metadata=meta,
                            attempts={"Open Access (Browser)": "success - opened in browser"},
                        )

                    # Wait briefly for any method to complete
                    done, not_done = concurrent.futures.wait(
                        list(future_to_method.keys()),
                        timeout=0.2,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )

                    # Group-level timeout
                    if time.time() - group_start > 60:
                        print("  Group timeout after 60s")
                        for f in future_to_method:
                            f.cancel()
                        break

                    # No method finished yet; loop again (to re-check cancellation)
                    if not done:
                        continue

                    # Process completed methods
                    for future in done:
                        method_name = future_to_method.pop(future)
                        try:
                            if future.cancelled():
                                continue
                            if future.result():
                                # Success! Cancel remaining
                                for f in not_done:
                                    f.cancel()

                                total_time = time.time() - start_time
                                print(f"\n✓ Success via {method_name} (total: {total_time:.1f}s)")
                                attempts[method_name] = "success"
                                return DownloadResult(
                                    success=True,
                                    source=method_name,
                                    filepath=output_file,
                                    metadata=meta,
                                    attempts=attempts,
                                )
                        except Exception:
                            # Errors are already logged inside wrapper
                            pass

                # If we exit the loop without returning, all methods in this group failed
                if wrapped_methods:
                    print(f"  All {len(wrapped_methods)} methods in group failed")
            finally:
                # Do not block on worker threads; let them finish in the background
                executor.shutdown(wait=False, cancel_futures=True)

        # All methods failed
        total_time = time.time() - start_time
        print(f"\nDownload failed: All acquisition methods failed (total time: {total_time:.1f}s)")
        return DownloadResult(
            success=False,
            error="All acquisition methods failed",
            metadata=meta,
            attempts=attempts
        )
    
    def _get_metadata(self, doi: str) -> Dict:
        """Get paper metadata from Crossref"""
        url = f"https://api.crossref.org/works/{doi}"
        response = self._get(url, timeout=10)
        data = response.json().get('message', {})
        
        # Extract basic metadata
        title = " ".join(data.get("title", []))
        year = None
        try:
            year = data.get("published-print", {}).get("date-parts", [[]])[0][0]
        except:
            pass
        
        journal = ""
        container = data.get("container-title", [])
        if container:
            journal = container[0]
        
        authors = []
        for author in data.get("author", []):
            name = f"{author.get('given', '')} {author.get('family', '')}".strip()
            if name:
                authors.append(name)
        
        return {
            "title": title,
            "year": year,
            "journal": journal,
            "authors": authors,
            "doi": doi,
            "raw": data,
        }
    
    def _try_crossref_links(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try direct PDF links from Crossref metadata - ENHANCED VERSION.
        
        Uses enhanced_crossref module if available for better link extraction.
        """
        try:
            # Try enhanced Crossref first if available
            if try_all_crossref_links:
                print("  Using enhanced Crossref extraction...")
                if try_all_crossref_links(doi, output_file, self.session):
                    return True
            
            # Fallback to standard Crossref
            # Get links from metadata
            raw_data = meta.get('raw', {})
            links = raw_data.get('link', [])
            
            if not links:
                # Fetch fresh from Crossref API
                url = f"https://api.crossref.org/works/{doi}"
                response = self._get(url, timeout=10)
                data = response.json().get('message', {})
                links = data.get('link', [])
            
            if not links:
                return False
            
            print(f"  Found {len(links)} Crossref links")
            
            # Organize links by type and priority
            pdf_links = []
            html_links = []
            xml_links = []
            other_links = []
            
            for link in links:
                content_type = link.get('content-type', '').lower()
                url = link.get('URL')
                if not url:
                    continue
                
                if 'pdf' in content_type:
                    pdf_links.append(url)
                elif 'html' in content_type or 'text/html' in content_type:
                    html_links.append(url)
                elif 'xml' in content_type:
                    xml_links.append(url)
                else:
                    other_links.append(url)
            
            # Track tried URLs to prevent infinite loops
            tried_urls = set()
            
            # Try PDF links first (highest priority)
            for pdf_url in pdf_links:
                if self._try_crossref_url(pdf_url, output_file, doi, 'PDF', tried_urls, depth=0):
                    return True
            
            # Try HTML links (might redirect to PDF or have embedded PDF)
            for html_url in html_links:
                if self._try_crossref_url(html_url, output_file, doi, 'HTML', tried_urls, depth=0):
                    return True
            
            # Try XML links (some publishers serve PDFs via XML endpoints)
            for xml_url in xml_links:
                if self._try_crossref_url(xml_url, output_file, doi, 'XML', tried_urls, depth=0):
                    return True
            
            # Try other links as last resort
            for other_url in other_links:
                if self._try_crossref_url(other_url, output_file, doi, 'other', tried_urls, depth=0):
                    return True
            
            return False
            
        except Exception as e:
            print(f"  Crossref links check failed: {type(e).__name__}")
            return False
    
    def _try_crossref_url(self, url: str, output_file: Path, doi: str, link_type: str, 
                          tried_urls: set, depth: int = 0, max_depth: int = 2) -> bool:
        """Try a single Crossref URL with publisher-specific handling.
        
        Args:
            url: URL to try
            output_file: Where to save PDF
            doi: Paper DOI
            link_type: Type of link (PDF, HTML, etc.)
            tried_urls: Set of already tried URLs (prevents infinite loops)
            depth: Current recursion depth
            max_depth: Maximum recursion depth (default 2)
        """
        try:
            # Prevent infinite recursion
            if depth > max_depth:
                return False
            
            # Skip if already tried
            if url in tried_urls:
                return False
            tried_urls.add(url)
            
            # Only show first level attempts
            if depth == 0:
                print(f"    Trying {link_type} link: {url[:70]}...")
            
            # Detect publisher for specialized handling
            publisher = self._detect_publisher(url)
            
            # Generate alternative URLs based on publisher
            urls_to_try = [url]
            alternatives = self._generate_publisher_alternatives(url, doi, publisher)
            # Filter out already tried URLs
            urls_to_try.extend([alt for alt in alternatives if alt not in tried_urls])
            
            total_urls = len(urls_to_try)
            for idx, attempt_url in enumerate(urls_to_try, 1):
                try:
                    # Mark as tried
                    tried_urls.add(attempt_url)
                    
                    # Show progress for alternatives (only at depth 0)
                    if depth == 0 and idx > 1:
                        progress = '█' * idx + '░' * (total_urls - idx)
                        print(f"      [{progress}] {idx}/{total_urls}", end='\r')
                    
                    # Build publisher-specific headers
                    headers = self._build_publisher_headers(attempt_url, publisher)
                    
                    # Make request
                    response = self.session.get(
                        attempt_url,
                        timeout=30,  # Reduced from 60
                        stream=True,
                        allow_redirects=True,
                        headers=headers
                    )
                    
                    # Check status
                    if response.status_code == 403:
                        if depth == 0 and idx == 1:
                            print(f"      ✗ Access forbidden (paywall)")
                        continue
                    elif response.status_code == 404:
                        continue
                    elif response.status_code != 200:
                        continue
                    
                    # Download content
                    content = b''
                    for chunk in response.iter_content(chunk_size=1024*1024):
                        if chunk:
                            content += chunk
                            if len(content) > 100*1024*1024:  # Max 100MB
                                break
                    
                    # Validate by magic bytes (not content-type)
                    if len(content) < 50*1024:
                        continue
                    
                    if not content.startswith(b'%PDF'):
                        # Check if HTML redirect page (only try once at depth 0)
                        if depth == 0 and b'<html' in content[:500].lower():
                            # Try to extract PDF link from HTML
                            pdf_link = self._extract_pdf_from_html(content, attempt_url)
                            if pdf_link and pdf_link not in tried_urls:
                                if depth == 0:
                                    print(f"\n      → Following redirect: {pdf_link[:60]}...")
                                # Recursively try the extracted link (depth + 1)
                                if self._try_crossref_url(pdf_link, output_file, doi, 'redirect', 
                                                         tried_urls, depth + 1, max_depth):
                                    return True
                        continue
                    
                    # Clear progress bar
                    if depth == 0 and idx > 1:
                        print(' ' * 80, end='\r')
                    
                    # Save and validate
                    with output_file.open('wb') as f:
                        f.write(content)
                    
                    if self._validate_pdf(output_file):
                        print(f"      ✓ Downloaded from Crossref ({link_type})")
                        return True
                    else:
                        output_file.unlink(missing_ok=True)
                
                except Exception as e:
                    continue
            
            # Clear progress bar
            if depth == 0 and total_urls > 1:
                print(' ' * 80, end='\r')
            
            return False
            
        except Exception:
            return False
    
    def _detect_publisher(self, url: str) -> str:
        """Detect publisher from URL."""
        url_lower = url.lower()
        
        if 'springer' in url_lower or 'nature.com' in url_lower:
            return 'springer'
        elif 'elsevier' in url_lower or 'sciencedirect' in url_lower:
            return 'elsevier'
        elif 'wiley' in url_lower:
            return 'wiley'
        elif 'ieee' in url_lower:
            return 'ieee'
        elif 'acs.org' in url_lower or 'pubs.acs.org' in url_lower:
            return 'acs'
        elif 'tandfonline' in url_lower:
            return 'taylorfrancis'
        elif 'sagepub' in url_lower:
            return 'sage'
        elif 'oxford' in url_lower:
            return 'oxford'
        elif 'cambridge' in url_lower:
            return 'cambridge'
        elif 'mdpi.com' in url_lower:
            return 'mdpi'
        elif 'frontiersin.org' in url_lower:
            return 'frontiers'
        else:
            return 'unknown'
    
    def _generate_publisher_alternatives(self, url: str, doi: str, publisher: str) -> list:
        """Generate alternative URLs based on publisher patterns."""
        alternatives = []
        
        if publisher == 'acs':
            # ACS has multiple PDF endpoints
            if '/doi/pdf/' in url:
                alternatives.append(url.replace('/doi/pdf/', '/doi/pdfdirect/'))
                alternatives.append(url.replace('/doi/pdf/', '/doi/pdfplus/'))
        
        elif publisher == 'springer':
            # Springer patterns
            if '/article/' in url:
                alternatives.append(url.replace('/article/', '/content/pdf/') + '.pdf')
            alternatives.append(url.split('?')[0] + '/pdf')  # Remove query params and add /pdf
        
        elif publisher == 'wiley':
            # Wiley patterns
            if '/doi/' in url and '/pdf' not in url:
                alternatives.append(url + '/pdf')
                alternatives.append(url + '/pdfdirect')
                alternatives.append(url + '/epdf')
        
        elif publisher == 'elsevier':
            # Elsevier patterns
            if '/pii/' in url:
                alternatives.append(url + '/pdfft')
                alternatives.append(url + '/pdf')
        
        elif publisher == 'mdpi':
            # MDPI is usually OA and has predictable URLs
            if '/htm' in url:
                alternatives.append(url.replace('/htm', '/pdf'))
        
        elif publisher == 'frontiers':
            # Frontiers is OA
            if '/articles/' in url:
                alternatives.append(url + '/pdf')
        
        return alternatives
    
    def _build_publisher_headers(self, url: str, publisher: str) -> dict:
        """Build publisher-specific headers."""
        base_headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/pdf,application/octet-stream,text/html,application/xhtml+xml,*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
        }
        
        # Add referer
        if '/doi/' in url:
            base_url = url.split('/doi/')[0]
            base_headers['Referer'] = base_url + '/'
        
        # Publisher-specific headers
        if publisher == 'springer':
            base_headers['Upgrade-Insecure-Requests'] = '1'
        elif publisher == 'wiley':
            base_headers['Sec-Fetch-Dest'] = 'document'
            base_headers['Sec-Fetch-Mode'] = 'navigate'
        
        return base_headers
    
    def _extract_pdf_from_html(self, html_content: bytes, base_url: str) -> Optional[str]:
        """Extract PDF link from HTML content."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Check meta tags
            for meta in soup.find_all('meta'):
                if meta.get('name') == 'citation_pdf_url':
                    pdf_url = meta.get('content')
                    if pdf_url:
                        if pdf_url.startswith('/'):
                            base = f"{base_url.split('/')[0]}//{base_url.split('/')[2]}"
                            return base + pdf_url
                        return pdf_url
            
            # Check for PDF links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.pdf' in href.lower() or '/pdf' in href.lower():
                    if href.startswith('/'):
                        base = f"{base_url.split('/')[0]}//{base_url.split('/')[2]}"
                        return base + href
                    elif href.startswith('http'):
                        return href
            
            return None
        except:
            return None
    
    def _try_landing_page_extraction(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try to access landing pages and extract PDF links - ENHANCED VERSION.
        
        Multi-strategy approach:
        1. Publisher-specific URL patterns (fast, no scraping needed)
        2. HTML meta tags and standard selectors
        3. Playwright for JS-rendered content (if available)
        4. Aggressive header spoofing and cookie handling
        """
        try:
            # Get landing page URL
            landing_url = f"https://doi.org/{doi}"
            print(f"  Trying landing page: {landing_url[:80]}...")
            
            # Follow redirects to get actual publisher URL
            response = self.session.get(landing_url, timeout=30, allow_redirects=True)
            actual_url = response.url
            publisher_domain = actual_url.split('/')[2] if len(actual_url.split('/')) > 2 else ''
            
            print(f"    Resolved to: {publisher_domain}")
            
            # STRATEGY 1: Try publisher-specific URL patterns first (fastest)
            print(f"    Strategy 1: Publisher-specific patterns")
            if self._try_publisher_patterns(doi, actual_url, output_file):
                return True
            
            # STRATEGY 2: Parse HTML for PDF links
            print(f"    Strategy 2: HTML parsing")
            if self._try_html_extraction(response, actual_url, output_file):
                return True
            
            # STRATEGY 3: Try Playwright for JS-heavy sites (if available)
            print(f"    Strategy 3: JavaScript rendering (Playwright)")
            if self._try_playwright_extraction(actual_url, output_file):
                return True
            
            return False
            
        except Exception as e:
            print(f"  Landing page extraction failed: {type(e).__name__}: {e}")
            return False
    
    def _try_publisher_patterns(self, doi: str, article_url: str, output_file: Path) -> bool:
        """Try publisher-specific URL patterns."""
        try:
            from publisher_patterns import guess_publisher_pdf_urls
            
            candidates = guess_publisher_pdf_urls(doi, article_url)
            if not candidates:
                return False
            
            print(f"      Found {len(candidates)} pattern candidates")
            
            for i, pdf_url in enumerate(candidates[:10], 1):  # Try top 10
                try:
                    print(f"      [{i}] {pdf_url[:70]}...")
                    
                    # Use aggressive headers
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'application/pdf,application/octet-stream,*/*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Referer': article_url,
                        'Origin': f"{article_url.split('/')[0]}//{article_url.split('/')[2]}",
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'same-origin',
                    }
                    
                    pdf_response = self.session.get(
                        pdf_url,
                        timeout=60,
                        stream=True,
                        allow_redirects=True,
                        headers=headers
                    )
                    
                    # Don't require content-type header (publishers often omit it)
                    # Instead, check magic bytes
                    content = b''
                    for chunk in pdf_response.iter_content(chunk_size=1024*1024):
                        if chunk:
                            content += chunk
                            if len(content) > 100*1024*1024:  # Max 100MB
                                break
                    
                    # Validate by magic bytes
                    if len(content) < 50*1024:
                        print(f"        ✗ Too small ({len(content)} bytes)")
                        continue
                    
                    if not content.startswith(b'%PDF'):
                        # Check if it's HTML (error page)
                        if content[:100].lower().find(b'<html') != -1:
                            print(f"        ✗ HTML page (not PDF)")
                            continue
                        print(f"        ✗ Not a PDF (magic bytes)")
                        continue
                    
                    # Save
                    with output_file.open('wb') as f:
                        f.write(content)
                    
                    if self._validate_pdf(output_file):
                        print(f"      ✓ Downloaded via publisher pattern")
                        return True
                    else:
                        output_file.unlink(missing_ok=True)
                
                except Exception as e:
                    print(f"        ✗ {type(e).__name__}")
                    continue
            
            return False
            
        except ImportError:
            print(f"      publisher_patterns module not available")
            return False
        except Exception as e:
            print(f"      Pattern matching failed: {type(e).__name__}")
            return False
    
    def _try_html_extraction(self, response: requests.Response, landing_url: str, output_file: Path) -> bool:
        """Extract PDF links from HTML."""
        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            pdf_links = []
            
            # 1. Check meta tags (most reliable)
            for meta in soup.find_all('meta'):
                if meta.get('name') in ['citation_pdf_url', 'bepress_citation_pdf_url']:
                    pdf_url = meta.get('content')
                    if pdf_url:
                        pdf_links.append(('meta', pdf_url))
                elif meta.get('property') == 'citation_pdf_url':
                    pdf_url = meta.get('content')
                    if pdf_url:
                        pdf_links.append(('meta', pdf_url))
            
            # 2. Look for PDF download buttons/links
            pdf_selectors = [
                'a[href*=".pdf"]',
                'a[href*="/pdf"]',
                'a[href*="/PDF"]',
                'a[href*="pdfdirect"]',
                'a[href*="epdf"]',
                'a[data-pdf-url]',
                'a[class*="pdf"]',
                'a[class*="download"]',
                'button[data-href*="pdf"]',
            ]
            
            for selector in pdf_selectors:
                for link in soup.select(selector):
                    href = link.get('href') or link.get('data-pdf-url') or link.get('data-href')
                    if href:
                        # Make absolute
                        if href.startswith('/'):
                            base = f"{landing_url.split('/')[0]}//{landing_url.split('/')[2]}"
                            href = base + href
                        elif not href.startswith('http'):
                            continue
                        
                        # Check if likely PDF
                        if any(x in href.lower() for x in ['.pdf', '/pdf', 'pdfdirect', 'epdf']):
                            pdf_links.append(('html', href))
            
            # Remove duplicates
            seen = set()
            unique_links = []
            for source, url in pdf_links:
                if url not in seen:
                    seen.add(url)
                    unique_links.append((source, url))
            
            if not unique_links:
                print(f"      No PDF links found in HTML")
                return False
            
            print(f"      Found {len(unique_links)} PDF links")
            
            # Try each link
            for source, pdf_url in unique_links:
                try:
                    print(f"      Trying {source}: {pdf_url[:70]}...")
                    
                    headers = {
                        'Referer': landing_url,
                        'User-Agent': self.session.headers.get('User-Agent'),
                        'Accept': 'application/pdf,*/*',
                    }
                    
                    pdf_response = self.session.get(pdf_url, timeout=60, stream=True, headers=headers)
                    
                    # Download and validate
                    content = b''
                    for chunk in pdf_response.iter_content(chunk_size=1024*1024):
                        if chunk:
                            content += chunk
                            if len(content) > 100*1024*1024:
                                break
                    
                    if len(content) < 50*1024 or not content.startswith(b'%PDF'):
                        continue
                    
                    with output_file.open('wb') as f:
                        f.write(content)
                    
                    if self._validate_pdf(output_file):
                        print(f"      ✓ Downloaded from HTML extraction")
                        return True
                    else:
                        output_file.unlink(missing_ok=True)
                
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            print(f"      HTML extraction failed: {type(e).__name__}")
            return False
    
    def _try_playwright_extraction(self, landing_url: str, output_file: Path) -> bool:
        """Use Playwright to render JS and extract PDF links."""
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
            
            print(f"      Launching browser...")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    viewport={'width': 1920, 'height': 1080},
                )
                page = context.new_page()
                
                # Navigate to page
                try:
                    response = page.goto(landing_url, wait_until='networkidle', timeout=30000)
                    
                    # CHECK: Is the page itself a PDF?
                    if response:
                        content_type = response.headers.get('content-type', '').lower()
                        if 'application/pdf' in content_type:
                            print(f"      Page is direct PDF (content-type: {content_type})")
                            content = response.body()
                            if len(content) >= 10 * 1024: # >10KB
                                with output_file.open('wb') as f:
                                    f.write(content)
                                if self._validate_pdf(output_file):
                                    print(f"      ✓ Downloaded direct PDF via Playwright")
                                    return True
                except PlaywrightTimeout:
                    page.goto(landing_url, wait_until='domcontentloaded', timeout=30000)
                
                # Wait a bit for dynamic content
                page.wait_for_timeout(2000)
                
                # Look for PDF download buttons/links
                pdf_selectors = [
                    'a[href*=".pdf"]',
                    'a[href*="/pdf"]',
                    'button:has-text("PDF")',
                    'a:has-text("Download PDF")',
                    'a:has-text("View PDF")',
                    '[data-pdf-url]',
                ]
                
                pdf_url = None
                for selector in pdf_selectors:
                    try:
                        element = page.query_selector(selector)
                        if element:
                            pdf_url = element.get_attribute('href') or element.get_attribute('data-pdf-url')
                            if pdf_url:
                                # Make absolute
                                if pdf_url.startswith('/'):
                                    base = f"{landing_url.split('/')[0]}//{landing_url.split('/')[2]}"
                                    pdf_url = base + pdf_url
                                break
                    except:
                        continue
                
                browser.close()
                
                if not pdf_url:
                    print(f"      No PDF link found via Playwright")
                    return False
                
                print(f"      Found PDF via Playwright: {pdf_url[:70]}...")
                
                # Download the PDF
                headers = {
                    'Referer': landing_url,
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                }
                
                response = self.session.get(pdf_url, timeout=60, stream=True, headers=headers)
                
                content = b''
                for chunk in response.iter_content(chunk_size=1024*1024):
                    if chunk:
                        content += chunk
                        if len(content) > 100*1024*1024:
                            break
                
                if len(content) >= 50*1024 and content.startswith(b'%PDF'):
                    with output_file.open('wb') as f:
                        f.write(content)
                    
                    if self._validate_pdf(output_file):
                        print(f"      ✓ Downloaded via Playwright")
                        return True
                    else:
                        output_file.unlink(missing_ok=True)
                
                return False
            
        except ImportError:
            print(f"      Playwright not available (install with: pip install playwright)")
            return False
        except Exception as e:
            print(f"      Playwright extraction failed: {type(e).__name__}")
            return False
    
    def _check_scihub_reachable(self) -> bool:
        """Check if any SciHub domain is reachable"""
        if self._scihub_reachable is not None:
            return self._scihub_reachable
        
        for domain in self.scihub_domains[:2]:  # Test first 2
            try:
                r = self.session.head(domain, timeout=3)
                if r.status_code < 500:
                    self._scihub_reachable = True
                    return True
            except:
                continue
        self._scihub_reachable = False
        return False
    
    def _validate_pdf(self, path: Path) -> bool:
        """Validate that a file is actually a PDF"""
        if not path.exists():
            return False
        
        if path.stat().st_size < 50 * 1024:  # < 50KB
            return False
        
        with path.open('rb') as f:
            header = f.read(1024)
            if not header.startswith(b'%PDF-'):
                return False
            
            # Check for HTML error pages
            header_lower = header.lower()
            if b'<html' in header_lower or b'<!doctype' in header_lower:
                return False
        
        return True
    
    def _try_scihub(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try to download from Sci-Hub with smart domain caching"""
        # Note: We removed the reachability check because it was too aggressive
        # and would skip Sci-Hub entirely if initial HEAD requests failed.
        # Better to try each domain and fail fast with short timeouts.
        
        # Try cached working domain first
        domains_to_try = []
        if self._working_scihub and self._working_scihub in self.scihub_domains:
            domains_to_try.append(self._working_scihub)
            domains_to_try.extend([d for d in self.scihub_domains if d != self._working_scihub])
        else:
            domains_to_try = self.scihub_domains
        
        for domain in domains_to_try:
            try:
                url = f"{domain}/{doi}"
                # print(f"  Trying Sci-Hub domain: {domain}...") # Verbose
                print(f"  {domain.replace('https://', '').replace('http://', '')}: ", end='', flush=True)
                
                try:
                    response = self.session.get(url, timeout=10, allow_redirects=True)
                    response.raise_for_status()
                except Exception:
                    print("✗ Offline")
                    continue
                
                # Check if direct PDF
                if 'pdf' in response.headers.get('content-type', '').lower():
                    with output_file.open('wb') as f:
                        f.write(response.content)
                    if self._validate_pdf(output_file):
                        return True
                
                # Parse HTML to find PDF link
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for PDF links with multiple approaches
                pdf_urls = []
                
                # Method 1: Direct PDF links in <a> tags
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if href and (href.lower().endswith('.pdf') or 'pdf' in href.lower()):
                        if href.startswith('/'):
                            href = domain + href
                        elif not href.startswith('http'):
                            href = domain + '/' + href if not href.startswith('/') else domain + href
                        pdf_urls.append(href)
                
                # Method 2: Check iframes (often contains the PDF)
                for iframe in soup.find_all('iframe'):
                    src = iframe.get('src', '')
                    if src and ('pdf' in src.lower() or src.endswith('.pdf')):
                        if src.startswith('//'):
                            src = 'https:' + src
                        elif src.startswith('/'):
                            src = domain + src
                        pdf_urls.append(src)
                
                # Method 3: Check for download buttons or onclick
                for button in soup.find_all(['button', 'div', 'a'], onclick=True):
                    onclick = button.get('onclick', '')
                    if 'pdf' in onclick.lower():
                        import re
                        url_match = re.search(r'https?://[^\s\'"]+\.pdf', onclick)
                        if url_match:
                            pdf_urls.append(url_match.group(0))
                
                # Method 4: Check for embedded PDF objects
                for embed in soup.find_all('embed', src=True):
                    src = embed['src']
                    if 'pdf' in src.lower():
                        if src.startswith('/'):
                            src = domain + src
                        pdf_urls.append(src)
                
                # Method 5: Try common Sci-Hub download patterns
                # Sci-Hub often uses patterns like /download/{server}/{id}/{hash}/{filename}.pdf
                import re
                # Look for any download links
                for link in soup.find_all('a', href=re.compile(r'/download/')):
                    href = link['href']
                    if href and not href.endswith('.pdf'):
                        # Try adding .pdf extension
                        pdf_urls.append(domain + href + '.pdf')
                    elif href:
                        pdf_urls.append(domain + href)
                
                # Method 6: Fallback - try direct download patterns
                # If no links found, try common Sci-Hub patterns
                if not pdf_urls:
                    # Try some common patterns that Sci-Hub uses
                    doi_clean = doi.replace('/', '_').replace('.', '_')
                    fallback_patterns = [
                        f"/download/moscow/1/{doi_clean}.pdf",
                        f"/download/berlin/1/{doi_clean}.pdf", 
                        f"/download/2024/1/{doi_clean}.pdf",
                        f"/downloads/{doi_clean}.pdf"
                    ]
                    for pattern in fallback_patterns:
                        pdf_urls.append(domain + pattern)
                
                # Remove duplicates
                pdf_urls = list(set(pdf_urls))
                
                if pdf_urls:
                    # print(f"    Found {len(pdf_urls)} potential PDF link(s)")
                    # for url in pdf_urls[:5]:  # Show first 5
                    #    print(f"      PDF: {url[:80]}...")
                    pass

                # Try PDF URLs
                total_links = len(pdf_urls)
                # if total_links > 0:
                #    print(f"    Checking {total_links} links: ", end='', flush=True)
                
                for i, pdf_url in enumerate(pdf_urls):
                    try:
                        # Progress bar character
                        print("█", end='', flush=True)
                        
                        pdf_response = self.session.get(pdf_url, timeout=15, allow_redirects=True)
                        if 'pdf' in pdf_response.headers.get('content-type', '').lower() or pdf_response.content.startswith(b'%PDF'):
                            with output_file.open('wb') as f:
                                f.write(pdf_response.content)
                            if self._validate_pdf(output_file):
                                print(f" ✓ Found!")
                                # print(f"  ✓ Downloaded from Sci-Hub")
                                # Cache this working domain
                                self._working_scihub = domain
                                return True
                    except Exception:
                        # print("x", end='', flush=True)
                        continue
                
                if total_links > 0:
                    print(" ✗", end='\n')
                
                if not pdf_urls:
                    # print(f"    No PDF links found on Sci-Hub page")
                    # Debug: show a bit of the HTML to see what's there
                    page_text = soup.get_text()[:500]
                    if 'captcha' in page_text.lower():
                        print(f" CAPTCHA", end='\n')
                        # If CAPTCHA detected, try opening in browser instead
                        if self._browser_callback:
                            print(f"      Opening Sci-Hub URL in browser for manual download")
                            try:
                                self._browser_callback(url)
                                self._browser_opened = True
                                return True  # Consider this success since user can download manually
                            except Exception:
                                pass
                    elif 'not found' in page_text.lower() or 'sorry' in page_text.lower():
                        print(f" Not found", end='\n')
                        return False  # Paper not in Sci-Hub at all, don't waste time on other domains
                    else:
                        print(f" No links", end='\n')
                        # If we got a valid page but no PDF links, try opening in browser
                        if self._browser_callback and len(page_text) > 100:  # Seems like a real page
                            print(f"      Opening Sci-Hub URL in browser for manual download")
                            try:
                                self._browser_callback(url)
                                self._browser_opened = True
                                return True  # Success via manual download
                            except Exception:
                                pass
            except Exception as e:
                print(f"    Domain {domain} failed: {type(e).__name__}")
                continue
        
        return False
    
    def _try_libgen(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try Library Genesis"""
        if self._check_cancel():  # Abort immediately if Stop was clicked
            return False
        try:
            if try_fetch_from_libgen:
                title = meta.get("title", "")
                authors = meta.get("authors", [])

                # Detect potential book/encyclopedia chapter from container title
                container = meta.get("container-title", "") or meta.get("journal", "") or ""
                is_book_chapter = any(
                    x in container.lower() for x in [
                        "encyclopedia",
                        "handbook",
                        "proceedings",
                        "conference",
                        "book",
                        "volume",
                    ]
                ) if container else False

                # 1) Standard LibGen path: use chapter title + author(s)
                source = try_fetch_from_libgen(doi, title, authors, output_file)
                if source and output_file.exists():
                    return True

                # 2) Extra chance for book chapters: search LibGen by book/encyclopedia title
                #    This may find the full volume even if the specific chapter is missing.
                if is_book_chapter and container and container != title:
                    try:
                        print(f"  📚 Book chapter detected; trying LibGen with book title: {container[:60]}...")
                        source_book = try_fetch_from_libgen(None, container, authors, output_file)
                        if source_book and output_file.exists():
                            return True
                    except Exception as e:
                        print(f"  LibGen (book-level) failed: {type(e).__name__}")
        except Exception as e:
            print(f"  LibGen failed: {type(e).__name__}")
        return False
    
    def _try_unpaywall(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try Unpaywall API for Open Access versions."""
        # Delegate to _try_open_access which handles Unpaywall
        return self._try_open_access(doi, output_file, meta)
    
    def _try_open_access(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try Unpaywall and other OA sources"""
        try:
            # Unpaywall API - use real email
            import os
            email = os.environ.get('UNPAYWALL_EMAIL', 'test@test.com')
            url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
            print(f"  Checking Unpaywall...")
            response = self.session.get(url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                is_oa = data.get('is_oa', False)
                print(f"    Paper is {'Open Access' if is_oa else 'not Open Access'}")
                
                if not is_oa:
                    return False
                
                # Try all OA locations (prioritize repositories like PMC)
                oa_locations = data.get('oa_locations', [])
                if oa_locations:
                    print(f"    Found {len(oa_locations)} OA location(s)")
                
                # Sort: repositories first (PMC, arXiv, etc.), then publisher
                oa_locations_sorted = sorted(
                    oa_locations,
                    key=lambda x: 0 if x.get('host_type') == 'repository' else 1
                )
                
                for location in oa_locations_sorted:
                    host_type = location.get('host_type', 'unknown')
                    pdf_url = location.get('url_for_pdf')
                    landing_url = location.get('url')
                    
                    # Try both PDF URL and landing URL
                    urls_to_try = []
                    if pdf_url:
                        urls_to_try.append(('PDF', pdf_url))
                    if landing_url and landing_url != pdf_url:
                        urls_to_try.append(('Landing', landing_url))
                    
                    if not urls_to_try:
                        continue
                    
                    for url_type, url in urls_to_try:
                        try:
                            print(f"    Trying {host_type} ({url_type}): {url[:80]}...")
                            
                            headers = {
                                'User-Agent': self.session.headers.get('User-Agent', 'Mozilla/5.0'),
                            }
                            if landing_url:
                                headers['Referer'] = landing_url
                            
                            pdf_response = self.session.get(url, timeout=60, stream=True, headers=headers, allow_redirects=True)
                            
                            # Check content type
                            content_type = pdf_response.headers.get('content-type', '').lower()
                            if 'html' in content_type and url_type == 'PDF':
                                print(f"      ✗ Got HTML instead of PDF")
                                continue
                            
                            pdf_response.raise_for_status()
                            
                            # If HTML, try to extract PDF link
                            if 'html' in content_type and url_type == 'Landing':
                                from bs4 import BeautifulSoup
                                soup = BeautifulSoup(pdf_response.content, 'html.parser')
                                # Look for PDF links
                                for link in soup.find_all('a', href=True):
                                    if 'pdf' in link['href'].lower():
                                        pdf_link = link['href']
                                        if not pdf_link.startswith('http'):
                                            from urllib.parse import urljoin
                                            pdf_link = urljoin(url, pdf_link)
                                        print(f"      Found PDF link: {pdf_link[:60]}...")
                                        # Try this PDF link
                                        pdf_resp = self.session.get(pdf_link, timeout=30)
                                        if pdf_resp.content.startswith(b'%PDF'):
                                            with output_file.open('wb') as f:
                                                f.write(pdf_resp.content)
                                            if self._validate_pdf(output_file):
                                                print(f"  ✓ Downloaded from {host_type}")
                                                return True
                                continue
                            
                            # Direct PDF download
                            with output_file.open('wb') as f:
                                for chunk in pdf_response.iter_content(chunk_size=1024*1024):
                                    if chunk:
                                        f.write(chunk)
                            
                            if self._validate_pdf(output_file):
                                print(f"  ✓ Downloaded from {host_type}")
                                return True
                            else:
                                print(f"      ✗ Invalid PDF")
                                output_file.unlink(missing_ok=True)
                        except Exception as e:
                            print(f"      ✗ Failed: {type(e).__name__}")
                            continue
        except Exception as e:
            print(f"  Unpaywall check failed: {e}")
        
        return False
    
    def _try_browser_download(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Use browser automation to download PDFs blocked by anti-bot protections"""
        try:
            # Short sleep to let Sci-Hub/Telegram win the race if they are fast (0.5-2s)
            # This prevents opening the browser unnecessarily for papers available in shadow libs.
            from src.core.cancellation import cancellable_sleep
            cancellable_sleep(3.0)
            
            from playwright.sync_api import sync_playwright
            
            # Get OA URL from Unpaywall first
            import os
            email = os.environ.get('UNPAYWALL_EMAIL', 'test@test.com')
            url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
            response = self.session.get(url, timeout=15)
            
            if response.status_code != 200:
                return False
            
            data = response.json()
            is_oa = bool(data.get('is_oa', False))
            print(f"  Paper is {'Open Access' if is_oa else 'not Open Access'} (Unpaywall)")

            # Record OA flag in metadata so GUI can decide about browser opening
            try:
                meta['is_oa'] = is_oa
            except Exception:
                pass

            if not is_oa:
                # Unpaywall says not OA. According to our strict semantics, a
                # paywalled publisher landing page MUST NOT be treated as
                # success. Do not open the paywalled page here; simply return
                # False so shadow libraries and other real full-text sources
                # can decide the outcome.
                return False
            
            # Get best OA location and PDF URL
            pdf_url = None
            oa_locations = data.get('oa_locations', [])
            best_location = None
            
            # Prioritize repository sources
            for location in sorted(oa_locations, key=lambda x: 0 if x.get('host_type') == 'repository' else 1):
                if location.get('url_for_pdf') or location.get('url'):
                    best_location = location
                    break

            if best_location is not None:
                pdf_url = best_location.get('url_for_pdf')
                landing_url = best_location.get('url')
                host_type = best_location.get('host_type', 'unknown')
                # Store a human-usable OA URL for the GUI to open if needed
                try:
                    meta['oa_url'] = landing_url or pdf_url
                except Exception:
                    pass
            else:
                return False
            
            # Try to download PDF first
            if pdf_url:
                try:
                    print(f"  Trying to download PDF from {host_type}: {pdf_url[:80]}...")
                    pdf_response = self.session.get(pdf_url, timeout=60, stream=True, allow_redirects=True)
                    
                    # Check if it's actually a PDF
                    content = b''
                    for chunk in pdf_response.iter_content(chunk_size=1024*1024):
                        if chunk:
                            content += chunk
                            if len(content) > 100*1024*1024:  # Max 100MB
                                break
                    
                    if content.startswith(b'%PDF') and len(content) > 50*1024:
                        with output_file.open('wb') as f:
                            f.write(content)
                        print(f"  ✓ Downloaded PDF from {host_type}")
                        return True
                    else:
                        print(f"  ✗ URL did not return a valid PDF")
                except Exception as e:
                    print(f"  ✗ PDF download failed: {type(e).__name__}")
            
            # If PDF download failed, try to extract PDF link from landing page
            if landing_url:
                try:
                    print(f"  Trying to extract PDF link from landing page: {landing_url[:80]}...")
                    page_response = self.session.get(landing_url, timeout=30)
                    
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(page_response.content, 'html.parser')
                    
                    # Look for PDF links
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if 'pdf' in href.lower() or 'download' in href.lower():
                            if not href.startswith('http'):
                                from urllib.parse import urljoin
                                href = urljoin(landing_url, href)
                            
                            try:
                                print(f"    Trying extracted link: {href[:80]}...")
                                pdf_response = self.session.get(href, timeout=60, stream=True, allow_redirects=True)
                                
                                content = b''
                                for chunk in pdf_response.iter_content(chunk_size=1024*1024):
                                    if chunk:
                                        content += chunk
                                        if len(content) > 100*1024*1024:
                                            break
                                
                                if content.startswith(b'%PDF') and len(content) > 50*1024:
                                    with output_file.open('wb') as f:
                                        f.write(content)
                                    print(f"  ✓ Downloaded PDF from extracted link")
                                    return True
                            except Exception:
                                continue
                    
                    print(f"  ✗ Could not find valid PDF link on landing page")
                except Exception as e:
                    print(f"  ✗ Landing page extraction failed: {type(e).__name__}")
        
        except ImportError:
            print("  Playwright not installed, skipping browser download")
        except Exception as e:
            print(f"  Browser download failed: {type(e).__name__}: {e}")
        
        return False
    
    def _try_semantic_scholar(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try Semantic Scholar V2 - Enhanced with multiple fields and fallbacks"""
        try:
            # V2 API with more fields
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
            params = {
                'fields': 'title,url,openAccessPdf,externalIds,isOpenAccess,publicationVenue'
            }
            response = self.session.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                # Try 1: Direct OA PDF
                oa_pdf = data.get('openAccessPdf')
                if oa_pdf and oa_pdf.get('url'):
                    print(f"  Found OA PDF via Semantic Scholar")
                    pdf_url = oa_pdf['url']
                    try:
                        pdf_response = self.session.get(pdf_url, timeout=60, stream=True)
                        pdf_response.raise_for_status()
                        
                        with output_file.open('wb') as f:
                            for chunk in pdf_response.iter_content(chunk_size=1024*1024):
                                if chunk:
                                    f.write(chunk)
                        
                        if self._validate_pdf(output_file):
                            return True
                        else:
                            output_file.unlink(missing_ok=True)
                    except Exception as e:
                        print(f"    OA PDF failed: {type(e).__name__}")
                
                # Try 2: Check if marked as OA, try alternative sources
                if data.get('isOpenAccess'):
                    print(f"  Paper marked as Open Access")
                    # Try ArXiv ID if available
                    external_ids = data.get('externalIds', {})
                    if external_ids.get('ArXiv'):
                        arxiv_id = external_ids['ArXiv']
                        arxiv_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                        print(f"  Trying ArXiv: {arxiv_id}")
                        try:
                            pdf_response = self.session.get(arxiv_url, timeout=30)
                            if pdf_response.status_code == 200 and pdf_response.content.startswith(b'%PDF'):
                                with output_file.open('wb') as f:
                                    f.write(pdf_response.content)
                                if self._validate_pdf(output_file):
                                    return True
                                else:
                                    output_file.unlink(missing_ok=True)
                        except Exception as e:
                            print(f"    ArXiv failed: {type(e).__name__}")
                    
                    # Try PubMed ID if available
                    if external_ids.get('PubMed'):
                        pmid = external_ids['PubMed']
                        print(f"  Trying PubMed Central: {pmid}")
                        # Will be handled by _try_pmc
                
        except Exception as e:
            print(f"  Semantic Scholar failed: {type(e).__name__}")
        
        return False
    
    def _try_annas_archive(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try Anna's Archive - THE BEST source for books and book chapters"""
        if self._check_cancel():  # Abort immediately if Stop was clicked
            return False
        try:
            from src.acquisition.annas_archive import try_fetch_from_annas_archive
            title = meta.get("title", "")
            authors = meta.get("authors", [])
            
            # Extract ISBN if available
            isbn = meta.get("ISBN", None)
            if not isbn and "isbn" in meta:
                isbn = meta["isbn"]
            
            # Detect if this might be a book chapter
            container = meta.get("container-title", "")
            is_book_chapter = any(x in container.lower() for x in ['encyclopedia', 'handbook', 'proceedings', 'conference', 'book', 'volume'])
            
            if is_book_chapter:
                print(f"  📖 Detected book chapter in: {container}")
            
            if isbn:
                print(f"  📚 Found ISBN: {isbn}")
            
            return try_fetch_from_annas_archive(doi, title, output_file, isbn, authors)
        except Exception as e:
            print(f"  Anna's Archive failed: {type(e).__name__}")
            return False
    
    def _try_repositories(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try open repositories: Zenodo, Figshare, OSF, institutional repos.
        
        NEW: Comprehensive repository hunting covering:
        - Zenodo (CERN, EU-funded)
        - Figshare (data + papers)
        - OSF Storage (project files)
        - Institutional repositories
        - Dataverse
        - DSpace/EPrints generic
        """
        if self._check_cancel():  # Abort immediately if Stop was clicked
            return False
        if try_fetch_from_repositories is None:
            print("  Repositories module unavailable, skipping...")
            return False
        
        title = meta.get("title", "")
        authors = meta.get("authors", [])

        if not title:
            return False

        # Detect potential book/encyclopedia chapter using container title
        container = meta.get("container-title", "") or meta.get("journal", "") or ""
        is_book_chapter = any(
            x in container.lower() for x in [
                "encyclopedia",
                "handbook",
                "proceedings",
                "conference",
                "book",
                "volume",
            ]
        ) if container else False
        
        try:
            # 1) Normal repository search with chapter title
            success = try_fetch_from_repositories(
                doi=doi,
                title=title,
                authors=authors,
                output_file=output_file,
                session=self.session
            )
            
            if success and self._validate_pdf(output_file):
                return True
            elif success:
                output_file.unlink(missing_ok=True)

            # 2) Extra pass for book chapters: search using container (book/encyclopedia) title
            if is_book_chapter and container and container != title:
                try:
                    print(f"  📚 Book chapter detected; trying repositories with book title: {container[:60]}...")
                    success_book = try_fetch_from_repositories(
                        doi=doi,
                        title=container,
                        authors=authors,
                        output_file=output_file,
                        session=self.session
                    )
                    if success_book and self._validate_pdf(output_file):
                        return True
                    elif success_book:
                        output_file.unlink(missing_ok=True)
                except Exception as e:
                    print(f"  Repository hunt (book-level) failed: {type(e).__name__}")
        
        except Exception as e:
            print(f"  Repository hunt failed: {type(e).__name__}")
        
        return False
    
    def _try_springer_enhanced(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try publisher-specific strategies.
        
        NEW: Comprehensive publisher exploitation covering:
        - Nature/Springer (epdf, SharedIt, accepted manuscripts)
        - Science/AAAS (FirstRelease, author copies)
        - Elsevier (SSRN, Mendeley Data)
        - Wiley (epdf, OnlineOpen)
        - IEEE (arnumber, proceedings)
        - ACS (AuthorChoice)
        - And more...
        """
        publisher = meta.get("publisher", "")
        title = meta.get("title", "")
        
        if not title:
            return False
        
        # Try NEW enhanced publisher module first
        if try_fetch_publisher_enhanced:
            try:
                success = try_fetch_publisher_enhanced(
                    doi=doi,
                    title=title,
                    publisher=publisher,
                    output_file=output_file,
                    session=self.session,
                    browser_callback=self._browser_callback,
                )
                if success and self._validate_pdf(output_file):
                    return True
                elif success:
                    output_file.unlink(missing_ok=True)
            except Exception as e:
                print(f"  Enhanced publisher strategies failed: {type(e).__name__}")
        
        # Fallback: legacy modules
        if not publisher:
            return False
        
        publisher_lower = publisher.lower()
        
        # Springer/Nature specific (legacy)
        if "springer" in publisher_lower or "nature" in publisher_lower:
            try:
                from src.acquisition.springer_enhanced import try_fetch_springer_enhanced
                if try_fetch_springer_enhanced(doi, title, output_file, self.session):
                    return True
            except Exception as e:
                print(f"  Legacy Springer module failed: {type(e).__name__}")
        
        # Other publishers (legacy)
        try:
            from src.acquisition.publisher_specific import try_publisher_specific
            if try_publisher_specific(publisher, doi, title, output_file, self.session):
                return True
        except Exception as e:
            print(f"  Legacy publisher module failed: {type(e).__name__}")
        
        return False
    
    def _try_preprints(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try comprehensive preprint & author version search.
        
        NEW: Uses enhanced preprints module covering:
        - arXiv, bioRxiv, medRxiv, chemRxiv
        - SSRN, OSF Preprints, Europe PMC
        - HAL, CORE
        - Crossref preprint relations
        """
        if self._check_cancel():  # Abort immediately if Stop was clicked
            return False
        if try_fetch_from_preprints_enhanced is None:
            # Fallback to basic implementation if enhanced module unavailable
            print("  Enhanced preprints module unavailable, skipping...")
            return False
        
        title = meta.get("title", "")
        authors = meta.get("authors", [])
        
        if not title:
            return False
        
        try:
            success = try_fetch_from_preprints_enhanced(
                doi=doi,
                title=title,
                authors=authors,
                output_file=output_file,
                session=self.session
            )
            
            if success and self._validate_pdf(output_file):
                return True
            elif success:
                output_file.unlink(missing_ok=True)
        
        except Exception as e:
            print(f"  Enhanced preprints failed: {type(e).__name__}")
        
        return False
    
    # FIX 3: DUPLICATE SCI-HUB DELETED (lines 2401-2424)
    # The real _try_scihub implementation is at line 1693
    # This was a dead wrapper trying to import non-existent src.acquisition.scihub
    
    def _try_pmc(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try PubMed Central"""
        if self._check_cancel():  # Abort immediately if Stop was clicked
            return False
        try:
            url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={doi}"
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            from xml.etree import ElementTree as ET
            root = ET.fromstring(response.content)
            
            if root.find('.//error') is None:
                for record in root.findall('.//record'):
                    for link in record.findall('.//link[@format="pdf"]'):
                        pdf_url = link.get('href')
                        if pdf_url:
                            pdf_response = self.session.get(pdf_url, timeout=60, stream=True)
                            pdf_response.raise_for_status()
                            
                            with output_file.open('wb') as f:
                                for chunk in pdf_response.iter_content(chunk_size=1024*1024):
                                    if chunk:
                                        f.write(chunk)
                            
                            if self._validate_pdf(output_file):
                                return True
        except:
            pass
        
        return False
    
    def _try_advanced_bypass(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try advanced bypass techniques (ResearchGate, Academia, Preprints, etc.)"""
        try:
            from src.acquisition.advanced_bypass import try_advanced_bypass
            
            title = meta.get("title", "")
            authors = meta.get("authors", [])
            
            if not title:
                return False
            
            return try_advanced_bypass(doi, title, authors, output_file)
            
        except ImportError:
            print("  Advanced bypass module not available")
            return False
        except Exception as e:
            print(f"  Advanced bypass failed: {type(e).__name__}")
            return False
    
    def _try_international(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try international sources - FIX 3: Standardized file handling"""
        if self._check_cancel():  # Abort immediately if Stop was clicked
            return False
        title = meta.get("title", "")
        if title and try_fetch_from_international_sources:
            tmp_file = Path(tempfile.mkstemp(suffix=".pdf")[1])
            try:
                source = try_fetch_from_international_sources(title, doi, tmp_file)
                if source and tmp_file.exists():
                    # FIX 3: Use shutil.move for consistent file handling
                    import shutil
                    shutil.move(str(tmp_file), str(output_file))
                    return True
            except:
                pass
            finally:
                try:
                    tmp_file.unlink()
                except:
                    pass
        return False
    
    def _try_google_scholar(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try Google Scholar - FIX 3: Standardized file handling"""
        if self._check_cancel():  # Abort immediately if Stop was clicked
            return False
        title = meta.get("title", "")
        if title and try_fetch_from_google_scholar:
            tmp_file = Path(tempfile.mkstemp(suffix=".pdf")[1])
            try:
                author = meta.get("authors", [""])[0] if meta.get("authors") else None
                year = meta.get("year")
                source = try_fetch_from_google_scholar(title, doi, tmp_file, author, year)
                if source and tmp_file.exists():
                    # FIX 3: Use shutil.move for consistent file handling
                    import shutil
                    shutil.move(str(tmp_file), str(output_file))
                    return True
            except:
                pass
            finally:
                try:
                    tmp_file.unlink()
                except:
                    pass
        return False
    
    def _try_multilang(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try multi-language search - DISABLED: Translation never works per user feedback"""
        print("  Multi-language search disabled - translation feature causes issues")
        return False
        
        # FIX 2: MULTILINGUAL OPTIMIZATION - Try both English and translated in parallel
        import concurrent.futures
        import shutil
        
        def search_with_title(search_title, label):
            """Helper to search with a specific title"""
            tmp_file = Path(tempfile.mkstemp(suffix=".pdf")[1])
            try:
                print(f"  → {label}: {search_title[:60]}...")
                source = try_fetch_with_multilang(search_title, doi, tmp_file, languages=['zh-CN', 'ru', 'ko'])
                if source and tmp_file.exists():
                    return (tmp_file, source, label)
                return None
            except Exception as e:
                print(f"  ✗ {label} failed: {type(e).__name__}")
                try:
                    tmp_file.unlink()
                except:
                    pass
                return None
        
        # FIX 2: Execute parallel searches (English + Translated)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            # Search 1: Original English title
            future_english = executor.submit(search_with_title, title, "English title")
            
            # Search 2: Translated title (let the module handle translation)
            # Note: The module will translate internally, we just provide the English title
            # This ensures we try multiple translation services/approaches
            future_translated = executor.submit(search_with_title, title, "Translated search")
            
            # Wait for first success (max 10 seconds total)
            for future in concurrent.futures.as_completed([future_english, future_translated], timeout=10):
                try:
                    result = future.result()
                    if result:
                        tmp_file, source, label = result
                        # FIX 3: Use shutil.move for file handling
                        shutil.move(str(tmp_file), str(output_file))
                        print(f"  ✓ Downloaded from {source} ({label})")
                        # Cancel the other search
                        for f in [future_english, future_translated]:
                            f.cancel()
                        return True
                except Exception:
                    continue
        
        return False
    
    def _try_chinese(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try Chinese academic sources - FIX 3: Standardized file handling"""
        title = meta.get("title", "")
        if title and try_fetch_chinese_sources:
            tmp_file = Path(tempfile.mkstemp(suffix=".pdf")[1])
            try:
                author = meta.get("authors", [""])[0] if meta.get("authors") else None
                source = try_fetch_chinese_sources(title, doi, tmp_file, author)
                if source and tmp_file.exists():
                    # FIX 3: Use shutil.move for consistent file handling
                    import shutil
                    shutil.move(str(tmp_file), str(output_file))
                    return True
            except:
                pass
            finally:
                try:
                    tmp_file.unlink()
                except:
                    pass
        return False
    
    def _try_deep_crawl(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try deep crawl of author pages and repositories - FIX 3: Standardized file handling"""
        title = meta.get("title", "")
        if title and try_fetch_deep_crawl:
            tmp_file = Path(tempfile.mkstemp(suffix=".pdf")[1])
            try:
                source = try_fetch_deep_crawl(title, doi, tmp_file, meta)
                if source and tmp_file.exists():
                    # FIX 3: Use shutil.move for consistent file handling
                    import shutil
                    shutil.move(str(tmp_file), str(output_file))
                    return True
            except:
                pass
            finally:
                try:
                    tmp_file.unlink()
                except:
                    pass
        return False
    
    def _try_europepmc(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try Europe PMC (3M+ OA biomedical papers) - NEW modular source"""
        try:
            from src.acquisition.europepmc import EuropePMCSource
            
            source = EuropePMCSource(session=self.session)
            result = source.try_acquire(doi, output_file, meta)
            
            return result.success if result else False
        except ImportError:
            print("  Europe PMC module not available")
            return False
        except Exception as e:
            print(f"  Europe PMC failed: {type(e).__name__}")
            return False
    
    def _try_core(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """Try CORE.ac.uk (200M+ aggregated papers) - NEW modular source"""
        try:
            from src.acquisition.core_ac_uk import CORESource
            
            # Check for API key
            import os
            api_key = os.getenv('CORE_API_KEY')
            if not api_key:
                # Silently skip if no API key configured
                return False
            
            source = CORESource(session=self.session, api_key=api_key)
            result = source.try_acquire(doi, output_file, meta)
            
            return result.success if result else False
        except ImportError:
            print("  CORE.ac.uk module not available")
            return False
        except Exception as e:
            print(f"  CORE.ac.uk failed: {type(e).__name__}")
            return False
    
    def _try_telegram_underground(self, doi: str, output_file: Path, meta: Dict) -> bool:
        """
        Try Telegram bots as an additional acquisition method.
        
        This uses bots like @scihubot, @libgen_scihub_bot, etc. via Telethon.
        """
        print(f"  🤖 Checking Telegram bots...")
        try:
            from src.acquisition.telegram_underground import TelegramUndergroundSource
            
            # Create source with config
            source = TelegramUndergroundSource(
                session=self.session,
                api_id=self.config.telegram.api_id if self.config and hasattr(self.config, 'telegram') else None,
                api_hash=self.config.telegram.api_hash if self.config and hasattr(self.config, 'telegram') else None,
                phone=self.config.telegram.phone if self.config and hasattr(self.config, 'telegram') else None,
                rate_limit_per_hour=self.config.telegram.rate_limit_per_hour if self.config and hasattr(self.config, 'telegram') else 20,
                bots=self.config.telegram.underground_bots if self.config and hasattr(self.config, 'telegram') else None
            )
            
            # Try to acquire
            result = source.try_acquire(doi, output_file, meta)
            
            if result.success:
                print(f"  ✓ [TELEGRAM] Success via {result.source}")
                return True
            else:
                # Log failure reason for debugging
                print(f"  ✗ [TELEGRAM] Failed: {result.error}")
                return False
                
        except ImportError:
            print("  [TELEGRAM] Telethon not installed (pip install telethon)")
            return False
        except Exception as e:
            print(f"  [TELEGRAM] Error: {type(e).__name__}: {str(e)}")
            return False
