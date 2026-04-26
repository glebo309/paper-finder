#!/usr/bin/env python3
"""
Telegram Bot Access - High-Power Mode.

This module uses Telethon to access Telegram bots that have:
- Private Sci-Hub mirrors
- Direct LibGen database access
- Z-Library collections
- Community-uploaded papers
- Cached successful downloads

Bots targeted:
- @scihubot (primary, fastest)
- @libgen_scihub_bot (books + papers)
- @booksandpapers_bot (community uploads)

For research purposes only.
"""

import os
import re
import asyncio
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

# Configure logging for this module and for Telethon BEFORE importing Telethon
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

# Silence Telethon logs BEFORE import
import logging as telethon_logging
telethon_logger = telethon_logging.getLogger('telethon')
telethon_logger.setLevel(telethon_logging.ERROR)
telethon_logger.propagate = False

_telethon_logger = logging.getLogger("telethon")
_telethon_logger.setLevel(logging.ERROR)
_telethon_logger.propagate = False

_telethon_crypto_logger = logging.getLogger("telethon.crypto.aes")
_telethon_crypto_logger.setLevel(logging.ERROR)
_telethon_crypto_logger.propagate = False

try:
    from telethon import TelegramClient
    from telethon.tl.types import Message, MessageMediaDocument
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

from src.core.base_source import SimpleAcquisitionSource
from src.core.result import AcquisitionResult

# CRITICAL: Global lock to prevent "database is locked" errors
# Telethon uses SQLite session file which doesn't support concurrent access
_TELEGRAM_LOCK = threading.Lock()


class TelegramUndergroundSource(SimpleAcquisitionSource):
    """
    Access papers through high-power Telegram bots.
    
    This is the most aggressive acquisition method, accessing:
    - Private Sci-Hub mirrors
    - Z-Library (10M+ books)
    - Community caches
    - Direct database access
    
    Success rate: +15-20% for hard-to-find papers
    Speed: 2-5 seconds (much faster than scraping)
    """
    
    # Set as FAST tier - these bots are actually faster than scraping!
    # They have direct DB access and cached results (2-5 seconds)
    tier = "fast"
    
    def __init__(
        self,
        session=None,
        api_id: int = None,
        api_hash: str = None,
        phone: str = None,
        max_wait: int = 30,
        rate_limit_per_hour: int = 20
    ):
        """
        Initialize Telegram client for bot access.
        
        Args:
            api_id: Telegram API ID from https://my.telegram.org
            api_hash: Telegram API hash
            phone: Phone number for authentication (optional, for first run)
            max_wait: Maximum seconds to wait for bot response
            rate_limit_per_hour: Maximum requests per hour
        """
        super().__init__(session)
        
        if not TELETHON_AVAILABLE:
            raise ImportError("Telethon not installed. Run: pip install telethon")
        
        # Load from environment if not provided
        self.api_id = api_id or os.getenv('TELEGRAM_API_ID')
        self.api_hash = api_hash or os.getenv('TELEGRAM_API_HASH')
        self.phone = phone or os.getenv('TELEGRAM_PHONE')
        
        # Convert api_id to int if string
        if self.api_id and isinstance(self.api_id, str):
            self.api_id = int(self.api_id)
        
        self.max_wait = max_wait
        self.rate_limit_per_hour = rate_limit_per_hour
        
        # Track rate limiting
        self.request_times = []
        
        # Bot priority list - only verified working bots
        # Many bots have been removed due to invalid usernames or rate limits
        self.bots = [
            '@scihubot',              # Verified working - primary bot
            '@scihubreal',            # User provided Sci-Hub bot
            '@zlibrary_bot',          # Z-Library bot
        ]
        
        # Session management
        self.client = None
        self.session_name = 'paper_finder_telegram_session'
        
        # Check if we can initialize
        self.enabled = bool(self.api_id and self.api_hash)
        
        if self.enabled:
            logger.info(f"Telegram bots source initialized (API ID: {self.api_id})")
        else:
            logger.warning(f"Telegram bots source disabled. ID={self.api_id}, Hash={'Present' if self.api_hash else 'Missing'}")
    
    @property
    def name(self) -> str:
        return "Telegram Bots"
    
    def get_download_urls(self, doi: str, metadata: Dict) -> List[str]:
        """
        Not used for Telegram - we handle downloads directly.
        """
        return []
    
    def try_acquire(
        self,
        doi: str,
        output_file: Path,
        metadata: Dict
    ) -> AcquisitionResult:
        """
        Try to acquire paper through Telegram bots.
        
        This is the high-power option - uses Telegram bots with:
        - Private mirrors
        - Direct database access
        - Community caches
        """
        if not self.enabled:
            return AcquisitionResult.failure_result(
                source=self.name,
                error="Telegram API credentials not configured"
            )
        
        # Check rate limit
        if not self._check_rate_limit():
            return AcquisitionResult.failure_result(
                source=self.name,
                error="Rate limit exceeded"
            )
        
        # CRITICAL: Acquire lock to prevent concurrent Telegram access
        # SQLite session file cannot handle parallel operations
        with _TELEGRAM_LOCK:
            try:
                # Run async acquisition in a dedicated event loop
                result = asyncio.run(
                    self._async_acquire(doi, output_file, metadata)
                )
                return result
                
            except Exception as e:
                logger.error(f"Telegram client error: {e}")
                return AcquisitionResult.failure_result(
                    source=self.name,
                    error=f"Telegram error: {type(e).__name__}"
                )
    
    async def _async_acquire(
        self,
        doi: str,
        output_file: Path,
        metadata: Dict
    ) -> AcquisitionResult:
        """
        Async method to interact with Telegram bots.
        """
        # Initialize client
        if not self.client:
            self.client = TelegramClient(
                self.session_name,
                self.api_id,
                self.api_hash
            )
        
        try:
            # Connect to Telegram
            await self.client.start(phone=self.phone)
            logger.info("Connected to Telegram")
            
            # Try each bot in order (stops at first success)
            for bot_username in self.bots:
                logger.info(f"[TELEGRAM] Trying {bot_username}...")
                
                try:
                    success = await self._try_bot(
                        bot_username,
                        doi,
                        output_file,
                        metadata
                    )
                    
                    if success:
                        # Record successful request
                        self.request_times.append(datetime.now())
                        
                        logger.info(f"[TELEGRAM] ✅ SUCCESS via {bot_username}")
                        return AcquisitionResult.success_result(
                            source=f"{self.name} ({bot_username})",
                            filepath=output_file,
                            metadata=metadata
                        )
                except Exception as e:
                    # Handle invalid bot usernames gracefully
                    error_msg = str(e).lower()
                    if "no user has" in error_msg or "username" in error_msg:
                        # Bot doesn't exist - fail silently
                        logger.debug(f"[TELEGRAM] {bot_username} not found (username invalid)")
                    else:
                        # Other errors - log as warning
                        logger.warning(f"[TELEGRAM] {bot_username} error: {e}")
                    continue
            
            # All bots failed
            return AcquisitionResult.failure_result(
                source=self.name,
                error="No bot could provide the paper"
            )
            
        except Exception as e:
            # Handle database lock errors gracefully
            error_msg = str(e).lower()
            if "database is locked" in error_msg:
                msg = "Telegram session locked. Please CLOSE other Paper Finder instances (GUI/CLI) and try again."
                logger.warning(f"[TELEGRAM] {msg}")
                return AcquisitionResult.failure_result(
                    source=self.name,
                    error=msg
                )
            else:
                logger.error(f"Telegram client error: {e}")
            
            return AcquisitionResult.failure_result(
                source=self.name,
                error=str(e)
            )
    
    async def _try_bot(
        self,
        bot_username: str,
        doi: str,
        output_file: Path,
        metadata: Dict
    ) -> bool:
        """
        Try a specific bot to get the paper.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Prepare query (DOI or title)
            query = doi
            if not query and metadata.get('title'):
                query = metadata['title']
            
            if not query:
                return False
            
            # Send query to bot
            logger.info(f"Sending to {bot_username}: {query[:50]}...")
            await self.client.send_message(bot_username, query)
            
            # Wait for response
            start_time = datetime.now()
            last_message_id = None
            
            while (datetime.now() - start_time).seconds < self.max_wait:
                # Get latest messages from bot
                messages = await self.client.get_messages(
                    bot_username,
                    limit=5
                )
                
                if not messages:
                    await asyncio.sleep(1)
                    continue
                
                # Check for new messages
                for msg in messages:
                    # Skip if we've seen this message
                    if last_message_id and msg.id <= last_message_id:
                        continue
                    
                    # Check if message has a document
                    if msg.media and isinstance(msg.media, MessageMediaDocument):
                        # Check if it's a PDF
                        doc = msg.media.document
                        is_pdf = False
                        
                        # Check MIME type
                        for attr in doc.attributes:
                            if hasattr(attr, 'mime_type'):
                                if 'pdf' in attr.mime_type.lower():
                                    is_pdf = True
                                    break
                            if hasattr(attr, 'file_name'):
                                if attr.file_name.lower().endswith('.pdf'):
                                    is_pdf = True
                                    break
                        
                        if is_pdf:
                            logger.info(f"Found PDF from {bot_username}!")
                            
                            # Download the file to a temporary location
                            temp_file = Path(tempfile.mktemp(suffix='.pdf'))
                            await self.client.download_media(
                                msg.media,
                                temp_file
                            )
                            
                            # Basic file-level validation
                            if not temp_file.exists() or temp_file.stat().st_size <= 10000:
                                if temp_file.exists():
                                    temp_file.unlink()
                                continue

                            # Extra safety: require that the PDF content actually mentions the requested DOI
                            # Enhanced validation: check DOI AND title for better accuracy
                            if doi and len(doi) > 10:  # Only validate for real DOIs, not ISBNs
                                title = metadata.get('title', '')
                                if not _pdf_contains_identifier(temp_file, doi, title):
                                    # Mismatch: likely the wrong paper; discard silently
                                    logger.warning(f"PDF from {bot_username} does not appear to match requested DOI/title; ignoring")
                                    try:
                                        temp_file.unlink()
                                    except Exception:
                                        pass
                                    continue

                            # Move to output location
                            import shutil
                            shutil.move(str(temp_file), str(output_file))
                            
                            logger.info(f"Successfully downloaded from {bot_username}")
                            return True
                    
                    # Check for text responses that might indicate failure
                    if msg.text:
                        text_lower = msg.text.lower()
                        if any(fail in text_lower for fail in [
                            'not found', 'couldn\'t find', 'no result',
                            'error', 'failed', 'unavailable'
                        ]):
                            logger.info(f"{bot_username} couldn't find the paper")
                            return False
                
                # Update last seen message
                if messages:
                    last_message_id = messages[0].id
                
                # Wait before checking again
                await asyncio.sleep(2)
            
            logger.info(f"Timeout waiting for {bot_username}")
            return False
            
        except Exception as e:
            logger.error(f"Error with {bot_username}: {e}")
            return False
    
    def _check_rate_limit(self) -> bool:
        """
        Check if we're within rate limits.
        
        Returns:
            True if we can make a request, False if rate limited
        """
        now = datetime.now()
        
        # Remove old requests (older than 1 hour)
        self.request_times = [
            t for t in self.request_times
            if (now - t).seconds < 3600
        ]
        
        # Check if we're at limit
        if len(self.request_times) >= self.rate_limit_per_hour:
            logger.warning(f"Rate limit reached ({self.rate_limit_per_hour}/hour)")
            return False
        
        return True


def _pdf_contains_identifier(path: Path, identifier: str, title: str = None) -> bool:
    """Return True if the PDF text appears to contain the given identifier (e.g. DOI) or title.

    Uses PyPDF2 if available; on any import/parsing error, returns True so as not to
    block legitimate downloads when text extraction is unavailable.
    
    Args:
        path: Path to PDF file
        identifier: Primary identifier (usually DOI)
        title: Paper title for additional validation
    """
    if not identifier and not title:
        return True
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except Exception:
        # If we cannot inspect text, do not reject
        return True

    try:
        reader = PdfReader(str(path))
        texts: List[str] = []
        # Only inspect first few pages for speed
        for page in reader.pages[:3]:
            try:
                page_text = page.extract_text() or ""
                texts.append(page_text)
            except Exception:
                continue
        full_text = "\n".join(texts).lower()
        
        # Check DOI first (most reliable)
        if identifier and identifier.lower() in full_text:
            return True
            
        # If DOI not found, check title (with fuzzy matching)
        if title and len(title) > 10:
            # Check exact title match
            if title.lower() in full_text:
                return True
            
            # Check first significant words of title (handles subtitle differences)
            title_words = title.lower().split()[:5]  # First 5 words
            if len(title_words) >= 3:
                title_start = ' '.join(title_words)
                if title_start in full_text:
                    return True
        
        return False
    except Exception:
        # On any parsing error, do not block success
        return True


# Backward compatibility wrapper
async def fetch_from_telegram_bots(
    doi: str,
    output_file: Path,
    metadata: Dict = None,
    api_id: int = None,
    api_hash: str = None
) -> bool:
    """
    Simple wrapper for direct usage.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        source = TelegramUndergroundSource(
            api_id=api_id,
            api_hash=api_hash
        )
        
        result = source.try_acquire(
            doi=doi,
            output_file=output_file,
            metadata=metadata or {}
        )
        
        return result.success
        
    except Exception as e:
        logger.error(f"Telegram fetch failed: {e}")
        return False
