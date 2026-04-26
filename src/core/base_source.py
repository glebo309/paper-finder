#!/usr/bin/env python3
"""
Base class and interface for acquisition sources.

All source modules should implement this interface for consistency.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional
import requests

from .result import AcquisitionResult
from .validation import validate_pdf


class AcquisitionSource(ABC):
    """
    Base class for acquisition sources.
    
    Subclasses must implement try_acquire() method.
    """
    
    def __init__(self, session: requests.Session = None):
        self.session = session or self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Create HTTP session with standard headers."""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        return session
    
    @abstractmethod
    def try_acquire(
        self,
        doi: str,
        output_file: Path,
        metadata: Dict
    ) -> AcquisitionResult:
        """
        Attempt to acquire paper from this source.
        
        Args:
            doi: DOI of paper
            output_file: Where to save PDF
            metadata: Paper metadata (title, authors, year, etc.)
        
        Returns:
            AcquisitionResult with success/failure status
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this source."""
        pass
    
    def validate_result(self, output_file: Path) -> bool:
        """Validate that output file is a valid PDF."""
        return validate_pdf(output_file)


class SimpleAcquisitionSource(AcquisitionSource):
    """
    Helper for simple sources that just need to implement download logic.
    
    Handles common patterns like:
    - Building URLs
    - Making requests
    - Validating results
    - Error handling
    """
    
    def try_acquire(
        self,
        doi: str,
        output_file: Path,
        metadata: Dict
    ) -> AcquisitionResult:
        """Standard acquisition flow with error handling."""
        try:
            # Get download URL(s)
            urls = self.get_download_urls(doi, metadata)
            if not urls:
                return AcquisitionResult.failure_result(
                    source=self.name,
                    error="No download URLs found"
                )
            
            # Try each URL
            for url in urls:
                if self._download_from_url(url, output_file):
                    if self.validate_result(output_file):
                        return AcquisitionResult.success_result(
                            source=self.name,
                            filepath=output_file,
                            metadata=metadata
                        )
                    else:
                        output_file.unlink(missing_ok=True)
            
            return AcquisitionResult.failure_result(
                source=self.name,
                error="All download attempts failed validation"
            )
            
        except Exception as e:
            return AcquisitionResult.failure_result(
                source=self.name,
                error=f"{type(e).__name__}: {str(e)}"
            )
    
    @abstractmethod
    def get_download_urls(self, doi: str, metadata: Dict) -> list[str]:
        """
        Get list of potential download URLs.
        
        Returns:
            List of URLs to try (in priority order)
        """
        pass
    
    def _download_from_url(self, url: str, output_file: Path) -> bool:
        """
        Download PDF from URL.
        
        Returns:
            True if download succeeded (doesn't validate PDF)
        """
        try:
            response = self.session.get(url, timeout=30, stream=True)
            response.raise_for_status()
            
            # Check content type
            content_type = response.headers.get('content-type', '').lower()
            if 'html' in content_type:
                return False
            
            # Download
            with output_file.open('wb') as f:
                for chunk in response.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
            
            return True
            
        except Exception:
            return False
