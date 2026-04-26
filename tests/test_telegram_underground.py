#!/usr/bin/env python3
"""
Test script for Telegram Underground access.

Tests if we can connect to Telegram and access the underground bots.
"""

import os
import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.acquisition.telegram_underground import TelegramUndergroundSource
from src.core.config import Config


async def test_telegram():
    """Test Telegram underground access."""
    print("=" * 60)
    print("TESTING TELEGRAM UNDERGROUND ACCESS")
    print("=" * 60)
    print()
    
    # Load config
    config = Config()
    
    # Check if configured
    if not config.telegram.api_id or not config.telegram.api_hash:
        print("❌ Not configured!")
        print()
        print("Please run: python setup_telegram_underground.py")
        print()
        print("Or set environment variables:")
        print("  export TELEGRAM_API_ID='your_id'")
        print("  export TELEGRAM_API_HASH='your_hash'")
        return False
    
    print(f"✅ API ID: {config.telegram.api_id}")
    print(f"✅ API Hash: {config.telegram.api_hash[:10]}...")
    print(f"✅ Underground enabled: {config.telegram.underground_enabled}")
    print(f"✅ Rate limit: {config.telegram.rate_limit_per_hour}/hour")
    print()
    print("Bots configured:")
    for bot in config.telegram.underground_bots:
        print(f"  • {bot}")
    print()
    
    # Test connection
    print("-" * 60)
    print("Testing connection to Telegram...")
    print()
    
    try:
        # Create source
        source = TelegramUndergroundSource(
            api_id=config.telegram.api_id,
            api_hash=config.telegram.api_hash,
            phone=config.telegram.phone,
            rate_limit_per_hour=config.telegram.rate_limit_per_hour
        )
        
        # Test DOI
        test_doi = "10.1038/nature12373"  # Popular paper, likely cached
        print(f"Test DOI: {test_doi}")
        print()
        
        # Create temp output
        output_file = Path("test_telegram_output.pdf")
        
        # Try to acquire
        print("Attempting to fetch paper...")
        print("(This may take 30 seconds)")
        print()
        
        result = await source._async_acquire(
            doi=test_doi,
            output_file=output_file,
            metadata={"title": "Test paper"}
        )
        
        if result.success:
            print("✅ SUCCESS!")
            print(f"   Source: {result.source}")
            if output_file.exists():
                size_kb = output_file.stat().st_size / 1024
                print(f"   File size: {size_kb:.1f} KB")
                print(f"   Saved to: {output_file}")
                
                # Clean up
                output_file.unlink()
            print()
            print("🎉 Telegram underground access is working!")
        else:
            print(f"❌ Failed: {result.error}")
            print()
            print("This might be normal if:")
            print("  • The bots don't have this specific paper")
            print("  • You haven't authenticated yet (check for login prompt)")
            print("  • Rate limits are in effect")
        
        return result.success
        
    except ImportError:
        print("❌ Telethon not installed!")
        print()
        print("Please run: pip install telethon")
        return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
        print("If this is your first run:")
        print("  • Check your phone for a Telegram code")
        print("  • The script may be waiting for input")
        return False


def main():
    """Main entry point."""
    # Run async test
    success = asyncio.run(test_telegram())
    
    print()
    print("=" * 60)
    if success:
        print("TEST PASSED! ✅")
        print()
        print("Underground access is working!")
        print("Your Paper Finder now has access to:")
        print("  • Private Sci-Hub mirrors")
        print("  • Z-Library (10M+ books)")
        print("  • Direct database access")
        print("  • Community caches")
    else:
        print("TEST INCOMPLETE")
        print()
        print("Check the error messages above.")
        print("You may need to:")
        print("  1. Run setup_telegram_underground.py")
        print("  2. Authenticate with Telegram (first run)")
        print("  3. Try a different test DOI")
    print("=" * 60)


if __name__ == "__main__":
    main()
