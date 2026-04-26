#!/usr/bin/env python3
"""
Telegram Bot Interface for Paper Finder.

Production-ready asynchronous Telegram bot that provides a world-class
user experience for paper acquisition via the modular PaperFinder engine.

Author: PaperFinder Team
Date: December 2024
"""

import os
import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Production Telegram Bot interface for PaperFinder.
    
    This class serves as the boundary layer between Telegram's async API
    and the PaperFinder core engine, providing real-time feedback and
    robust file management.
    """
    
    def __init__(self, config):
        """
        Initialize the Telegram bot with strict configuration enforcement.
        
        Args:
            config: AppConfig object with telegram.token and other settings
            
        Raises:
            ValueError: If telegram.token is missing from configuration
        """
        # Strict configuration validation
        if not hasattr(config, 'telegram') or not config.telegram.token:
            raise ValueError(
                "Telegram bot token is missing. "
                "Please set TELEGRAM_BOT_TOKEN environment variable or "
                "configure telegram.token in config.yaml"
            )
        
        self.config = config
        self.token = config.telegram.token
        
        # Initialize PaperFinder with configuration
        from paper_finder import PaperFinder
        self.finder = PaperFinder(config=config, silent_init=True)
        
        # Setup temporary directory with robust path logic
        self.temp_dir = self._setup_temp_directory()
        
        # Track active searches for proper cleanup
        self.active_searches = {}
    
    def _setup_temp_directory(self) -> Path:
        """
        Setup secure temporary directory for PDF downloads.
        
        Returns:
            Path object pointing to the temporary directory
        """
        # Check environment variable first
        temp_base = os.environ.get('PAPER_FINDER_TEMP', tempfile.gettempdir())
        temp_dir = Path(temp_base) / 'paper_finder_bot'
        
        # Ensure directory exists with proper permissions
        temp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        
        logger.info(f"Temporary directory initialized: {temp_dir}")
        return temp_dir
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /start command with comprehensive bot introduction.
        
        Provides users with clear instructions on how to use the bot
        and what input formats are accepted.
        """
        welcome_message = (
            "🎓 **Welcome to Paper Finder Helper Bot** (@paper_finder_helper_bot)\n\n"
            "I can help you find academic papers from multiple sources including:\n"
            "• Open Access repositories\n"
            "• Preprint servers (arXiv, bioRxiv, etc.)\n"
            "• PubMed Central\n"
            "• Institutional repositories\n"
            "• And many more!\n\n"
            "**How to use:**\n"
            "Simply send me one of the following:\n\n"
            "📌 **DOI**: `10.1038/nature12373`\n"
            "📌 **URL**: `https://doi.org/10.1038/nature12373`\n"
            "📌 **Citation**: `Nature 2013 Higgs boson`\n\n"
            "I'll search through 20+ sources in parallel to find your paper!\n\n"
            "💡 **Tip**: For best results, use DOIs when available."
        )
        
        await update.message.reply_text(
            welcome_message,
            parse_mode='Markdown'
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /help command with usage instructions.
        """
        help_text = (
            "📚 **Paper Finder Help**\n\n"
            "**Commands:**\n"
            "/start - Welcome message and instructions\n"
            "/help - This help message\n"
            "/status - Check bot status\n\n"
            "**Finding papers:**\n"
            "Just send me a DOI, URL, or citation directly!\n\n"
            "**Examples:**\n"
            "• `10.1126/science.1260062`\n"
            "• `https://doi.org/10.1038/s41586-019-1666-5`\n"
            "• `Cell 2019 CRISPR prime editing`\n\n"
            "**Issues?**\n"
            "If a paper can't be found, it might be:\n"
            "• Very recently published\n"
            "• Behind a paywall with no OA version\n"
            "• Not indexed in our sources yet"
        )
        
        await update.message.reply_text(
            help_text,
            parse_mode='Markdown'
        )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle /status command to check bot and pipeline status.
        """
        # Check pipeline status
        sources_count = len(self.finder.pipeline.get_registered_sources())
        
        status_message = (
            "✅ **Bot Status: Operational**\n\n"
            f"**Pipeline:**\n"
            f"• Active sources: {sources_count}\n"
            f"• Parallel workers: {self.config.network.max_workers}\n"
            f"• Cache: {'Enabled' if self.finder.cache else 'Disabled'}\n\n"
            f"**Temp directory:** `{self.temp_dir}`\n"
            f"**Active searches:** {len(self.active_searches)}"
        )
        
        await update.message.reply_text(
            status_message,
            parse_mode='Markdown'
        )
    
    async def _handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle text input for paper acquisition with real-time feedback.
        
        This is the core handler that processes user requests, manages
        the acquisition pipeline, and provides dynamic status updates.
        """
        input_text = update.message.text.strip()
        chat_id = update.effective_chat.id
        message_id = None
        
        # Validate input
        if not input_text:
            await update.message.reply_text(
                "❌ Please provide a DOI, URL, or citation to search for."
            )
            return
        
        # Generate unique temporary file path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_filename = f"paper_{chat_id}_{timestamp}.pdf"
        temp_path = self.temp_dir / temp_filename
        
        # Track this search
        search_id = f"{chat_id}_{timestamp}"
        self.active_searches[search_id] = temp_path
        
        try:
            # Send initial searching message (will be edited with updates)
            status_message = await update.message.reply_text(
                "🔍 **Searching...**\n\n"
                "_Initializing pipeline..._",
                parse_mode='Markdown'
            )
            message_id = status_message.message_id
            
            # Create progress callback for real-time updates
            async def progress_callback(stage: str, message: str):
                """Update the status message with pipeline progress."""
                try:
                    status_text = (
                        f"🔍 **Searching...**\n\n"
                        f"**Stage:** {stage}\n"
                        f"**Status:** {message}"
                    )
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=status_text,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.warning(f"Failed to update progress: {e}")
            
            # Execute acquisition with async wrapper
            loop = asyncio.get_event_loop()
            
            # Run PaperFinder.acquire in thread pool (it's sync)
            result = await loop.run_in_executor(
                None,
                lambda: self.finder.acquire(
                    input_text,
                    output_path=str(temp_path)
                )
            )
            
            # Process result based on outcome
            if result.success and result.filepath and Path(result.filepath).exists():
                # Success: PDF acquired
                await self._handle_success(
                    context,
                    chat_id,
                    message_id,
                    result,
                    Path(result.filepath)
                )
            
            elif result.success and hasattr(result, 'browser_opened') and result.browser_opened:
                # Open Access link (browser would open in GUI mode)
                await self._handle_browser_link(
                    context,
                    chat_id,
                    message_id,
                    result
                )
            
            else:
                # Failure: No PDF found
                await self._handle_failure(
                    context,
                    chat_id,
                    message_id,
                    result
                )
        
        except Exception as e:
            # Handle unexpected errors gracefully
            logger.error(f"Error during acquisition: {e}", exc_info=True)
            
            error_text = (
                "❌ **Error**\n\n"
                f"An unexpected error occurred: {type(e).__name__}\n"
                f"Please try again or contact support if the issue persists."
            )
            
            try:
                if message_id:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=error_text,
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        error_text,
                        parse_mode='Markdown'
                    )
            except Exception as edit_error:
                logger.error(f"Failed to send error message: {edit_error}")
        
        finally:
            # Guaranteed cleanup: Remove temporary file
            if temp_path.exists():
                try:
                    temp_path.unlink()
                    logger.info(f"Cleaned up temporary file: {temp_path}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to cleanup {temp_path}: {cleanup_error}")
            
            # Remove from active searches
            if search_id in self.active_searches:
                del self.active_searches[search_id]
    
    async def _handle_success(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        message_id: int,
        result,
        filepath: Path
    ) -> None:
        """
        Handle successful PDF acquisition.
        
        Updates status message and sends the PDF document with metadata.
        """
        # Update status message
        success_text = (
            f"✅ **Success!**\n\n"
            f"**Source:** {result.source}\n"
            f"**File size:** {filepath.stat().st_size / 1024:.1f} KB"
        )
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=success_text,
            parse_mode='Markdown'
        )
        
        # Prepare document caption with metadata
        caption_parts = []
        
        if result.metadata:
            if result.metadata.get('title'):
                caption_parts.append(f"📄 {result.metadata['title'][:100]}")
            if result.metadata.get('doi'):
                caption_parts.append(f"DOI: {result.metadata['doi']}")
            if result.metadata.get('year'):
                caption_parts.append(f"Year: {result.metadata['year']}")
        
        caption_parts.append(f"Source: {result.source}")
        caption = "\n".join(caption_parts)
        
        # Generate clean filename from metadata
        if result.metadata and result.metadata.get('title'):
            clean_title = "".join(
                c for c in result.metadata['title'][:50]
                if c.isalnum() or c in ' -_'
            ).strip()
            filename = f"{clean_title}.pdf"
        else:
            filename = f"paper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        # Send the PDF document
        with open(filepath, 'rb') as pdf_file:
            await context.bot.send_document(
                chat_id=chat_id,
                document=pdf_file,
                filename=filename,
                caption=caption[:1024]  # Telegram caption limit
            )
    
    async def _handle_browser_link(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        message_id: int,
        result
    ) -> None:
        """
        Handle Open Access papers that would open in browser.
        
        Provides the direct URL to the user since bot cannot open browser.
        """
        # Extract URL from result
        url = result.error if hasattr(result, 'error') and 'http' in str(result.error) else None
        
        browser_text = (
            "🌐 **Open Access Paper Found**\n\n"
            "This paper is available through your browser.\n"
        )
        
        if url:
            browser_text += f"**Direct link:** {url}\n\n"
        
        browser_text += (
            "_Note: The bot cannot directly download browser-only content. "
            "Please click the link above to access the paper._"
        )
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=browser_text,
            parse_mode='Markdown',
            disable_web_page_preview=False
        )
    
    async def _handle_failure(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        message_id: int,
        result
    ) -> None:
        """
        Handle failed acquisition attempts.
        
        Provides clear feedback about what went wrong.
        """
        failure_text = (
            "❌ **Paper Not Found**\n\n"
        )
        
        if hasattr(result, 'source') and result.source:
            failure_text += f"**Last source tried:** {result.source}\n"
        
        if hasattr(result, 'error') and result.error:
            failure_text += f"**Reason:** {result.error}\n\n"
        else:
            failure_text += (
                "The paper could not be found in any of our sources.\n\n"
            )
        
        failure_text += (
            "_This might be because the paper is:_\n"
            "• Very recently published\n"
            "• Behind a paywall with no OA version\n"
            "• Not yet indexed in our sources"
        )
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=failure_text,
            parse_mode='Markdown'
        )
    
    def run(self) -> None:
        """
        Start the bot with long polling.
        
        Sets up handlers and begins the async event loop.
        """
        # Create application with token
        application = Application.builder().token(self.token).build()
        
        # Register command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("status", self.status_command))
        
        # Register text message handler for paper requests
        application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self._handle_text_input
            )
        )
        
        # Start the bot with long polling
        logger.info("Starting Telegram bot with long polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


def run_telegram_bot(config) -> None:
    """
    Entry point for running the Telegram bot.
    
    Args:
        config: AppConfig object with necessary configuration
    """
    try:
        bot = TelegramBot(config)
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)
        raise
