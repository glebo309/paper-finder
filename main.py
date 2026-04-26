#!/usr/bin/env python3
"""
Paper Finder - Main Entry Point

Multi-mode application supporting GUI, CLI, and Telegram bot interfaces.
"""

import sys
import argparse
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point with subcommand support."""
    parser = argparse.ArgumentParser(
        prog='paper-finder',
        description='Academic Paper Acquisition System - Find papers from 20+ sources'
    )
    
    # Add subparsers for different modes
    subparsers = parser.add_subparsers(
        dest='command',
        help='Available commands'
    )
    
    # GUI mode (default)
    gui_parser = subparsers.add_parser(
        'gui',
        help='Launch graphical interface (default)'
    )
    
    # CLI acquisition mode
    acquire_parser = subparsers.add_parser(
        'acquire',
        help='Acquire a paper via command line'
    )
    acquire_parser.add_argument(
        'reference',
        help='DOI, URL, or citation to search for'
    )
    acquire_parser.add_argument(
        '--output',
        '-o',
        help='Output directory for PDF',
        default='downloads'
    )
    acquire_parser.add_argument(
        '--config',
        '-c',
        help='Configuration file path',
        default='config.yaml'
    )
    
    # Telegram bot mode
    bot_parser = subparsers.add_parser(
        'bot',
        help='Run Telegram bot interface'
    )
    bot_parser.add_argument(
        '--config',
        '-c',
        help='Configuration file path',
        default='config.yaml'
    )
    bot_parser.add_argument(
        '--token',
        help='Telegram bot token (overrides config/env)',
        default=None
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Default to GUI if no command specified
    if args.command is None:
        args.command = 'gui'
    
    # Execute based on command
    if args.command == 'gui':
        # Launch GUI
        from gui import main as gui_main
        gui_main()
    
    elif args.command == 'acquire':
        # CLI acquisition
        from paper_finder import PaperFinder
        from src.core.config import load_config
        
        try:
            # Load configuration
            config_path = Path(args.config)
            if config_path.exists():
                config = load_config(str(config_path))
            else:
                config = None
            
            # Initialize finder
            finder = PaperFinder(config=config, silent_init=True)
            
            # Create output directory if needed
            output_dir = Path(args.output)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Acquire paper
            print(f"🔍 Searching for: {args.reference}")
            result = finder.acquire(
                args.reference,
                output_dir=str(output_dir)
            )
            
            # Report result
            if result.success:
                if result.filepath:
                    print(f"✅ Success! Paper saved to: {result.filepath}")
                    print(f"   Source: {result.source}")
                else:
                    print(f"✅ Paper opened in browser (Open Access)")
            else:
                print(f"❌ Failed to find paper")
                if result.error:
                    print(f"   Error: {result.error}")
            
            # Exit with appropriate code
            sys.exit(0 if result.success else 1)
            
        except Exception as e:
            logger.error(f"Acquisition failed: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            sys.exit(1)
    
    elif args.command == 'bot':
        # Telegram bot mode
        import os
        from src.core.config import load_config, Config
        from src.cli.telegram_bot import run_telegram_bot
        
        try:
            # Load configuration
            config_path = Path(args.config)
            if config_path.exists():
                config = load_config(str(config_path))
            else:
                # Create minimal config
                config = Config()
            
            # Override token if provided via CLI
            if args.token:
                if not hasattr(config, 'telegram'):
                    from types import SimpleNamespace
                    config.telegram = SimpleNamespace()
                config.telegram.token = args.token
            elif not hasattr(config, 'telegram') or not config.telegram.token:
                # Try environment variable
                token = os.environ.get('TELEGRAM_BOT_TOKEN')
                if token:
                    if not hasattr(config, 'telegram'):
                        from types import SimpleNamespace
                        config.telegram = SimpleNamespace()
                    config.telegram.token = token
                else:
                    print("❌ Error: Telegram bot token not provided")
                    print("   Set TELEGRAM_BOT_TOKEN environment variable or use --token flag")
                    sys.exit(1)
            
            # Run the bot
            print("🤖 Starting Telegram bot...")
            print(f"   Bot: @paper_finder_helper_bot")
            print("   Mode: Long polling")
            print("   Press Ctrl+C to stop")
            
            run_telegram_bot(config)
            
        except KeyboardInterrupt:
            print("\n👋 Bot stopped")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Bot failed: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            sys.exit(1)


if __name__ == '__main__':
    main()
