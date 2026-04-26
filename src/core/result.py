#!/usr/bin/env python3
"""
Standardized result types for acquisition pipeline.

All source modules should return AcquisitionResult for consistency.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict


@dataclass
class AcquisitionResult:
    """Result of a single acquisition attempt."""
    success: bool
    source: str = ""
    error: Optional[str] = None
    filepath: Optional[Path] = None
    metadata: Optional[Dict] = None
    attempts: Dict[str, str] = field(default_factory=dict)
    
    @classmethod
    def success_result(cls, source: str, filepath: Path, metadata: Dict = None) -> "AcquisitionResult":
        """Create a success result."""
        return cls(
            success=True,
            source=source,
            filepath=filepath,
            metadata=metadata or {},
            attempts={source: "success"}
        )
    
    @classmethod
    def failure_result(cls, source: str, error: str, metadata: Dict = None) -> "AcquisitionResult":
        """Create a failure result."""
        return cls(
            success=False,
            source=source,
            error=error,
            metadata=metadata or {},
            attempts={source: f"failed: {error}"}
        )
    
    @classmethod
    def browser_result(cls, source: str, metadata: Dict = None) -> "AcquisitionResult":
        """Create a result for browser-opened papers (OA)."""
        return cls(
            success=True,
            source=source,
            filepath=None,  # No file, opened in browser
            metadata=metadata or {},
            attempts={source: "opened in browser"}
        )


# Maintain backward compatibility with existing DownloadResult
DownloadResult = AcquisitionResult
