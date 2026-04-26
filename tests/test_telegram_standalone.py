#!/usr/bin/env python3
"""
Standalone test for Telegram Bot acquisition.
Run this to verify Telegram connectivity and downloading.
"""

import sys
import logging
import shutil
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper_finder import PaperFinder

# Configure logging to see Telegram output
logging.basicConfig(level=logging.INFO)

def test_telegram():
    print("="*60)
    print("TESTING TELEGRAM BOTS")
    print("="*60)
    
    # Initialize PaperFinder (loads config)
    try:
        finder = PaperFinder()
    except Exception as e:
        print(f"Failed to initialize PaperFinder: {e}")
        return

    # Check if Telegram is enabled in config
    if not finder.config or not hasattr(finder.config, 'telegram'):
        print("❌ Telegram config missing in config.yaml")
        return
    
    if not finder.config.telegram.underground_enabled:
        print("❌ Telegram underground_enabled is False in config.yaml")
        return
        
    if not finder.config.telegram.api_id:
        print("❌ Telegram api_id missing in config.yaml")
        return

    print(f"✅ Telegram enabled with API ID: {finder.config.telegram.api_id}")
    print(f"Phone: {finder.config.telegram.phone}")
    
    # Test case: Book - Kuhn "The Structure of Scientific Revolutions"
    # Telegram bots are often best for books!
    doi = "978-0226458083" 
    output_file = Path("test_telegram_book.pdf")
    
    # Clean up previous run
    if output_file.exists():
        output_file.unlink()
    
    print(f"\nAttempting to fetch Book ISBN: {doi}")
    
    # Call the method directly
    meta = {
        "title": "The Structure of Scientific Revolutions",
        "year": 1962,
        "author": "Thomas Kuhn"
    }
    
    try:
        print("Calling _try_telegram_underground...")
        success = finder._try_telegram_underground(doi, output_file, meta)
        
        if success:
            print(f"\n✅ SUCCESS! PDF saved to: {output_file}")
            if output_file.exists():
                size = output_file.stat().st_size
                print(f"   File size: {size} bytes")
            else:
                print("   ⚠️  Success reported but file missing?")
        else:
            print("\n❌ FAILED - Telegram bots could not retrieve the paper.")
            
    except Exception as e:
        print(f"\n❌ EXCEPTION during execution: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_telegram()
