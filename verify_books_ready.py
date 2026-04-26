#!/usr/bin/env python3
"""
Quick verification that Telegram underground is ready for books.
"""

from pathlib import Path
from src.core.config import get_config

print("=" * 60)
print("TELEGRAM BOTS - BOOKS READY CHECK")
print("=" * 60)
print()

# Check config file
config_file = Path("config.yaml")
if config_file.exists():
    print(f"✅ Config file exists: {config_file}")
else:
    print(f"❌ Config file missing: {config_file}")
    print("   Run: python auto_enable_underground.py")
    exit(1)

# Load config
config = get_config()

print(f"✅ Config loaded successfully")
print()

# Check Telegram settings
print("Telegram Underground Settings:")
print(f"  Enabled: {config.telegram.underground_enabled}")
print(f"  API ID: {config.telegram.api_id}")
print(f"  API Hash: {'*' * 10}... (hidden)")
print(f"  Phone: {config.telegram.phone}")
print(f"  Rate limit: {config.telegram.rate_limit_per_hour}/hour")
print(f"  Bots configured: {len(config.telegram.underground_bots)}")
print()

if not config.telegram.underground_enabled:
    print("❌ Underground is DISABLED")
    print("   Run: python auto_enable_underground.py")
    exit(1)

if not config.telegram.api_id or not config.telegram.api_hash:
    print("❌ Missing API credentials")
    print("   Run: python setup_telegram_underground.py")
    exit(1)

print("✅ Telegram bots are ENABLED and configured!")
print()

# Test PaperFinder initialization
print("Testing PaperFinder initialization...")
from paper_finder import PaperFinder

finder = PaperFinder(silent_init=True)

if finder.config and hasattr(finder.config, 'telegram'):
    print(f"✅ PaperFinder has config")
    print(f"✅ Telegram enabled in finder: {finder.config.telegram.underground_enabled}")
    print(f"✅ API ID in finder: {finder.config.telegram.api_id}")
else:
    print("❌ PaperFinder config not loaded properly")
    exit(1)

print()
print("=" * 60)
print("✅ ALL CHECKS PASSED!")
print("=" * 60)
print()
print("Your system is ready to use Telegram bots for:")
print("  • Papers (parallel with other sources)")
print("  • Books (after Anna's Archive + LibGen)")
print("  • Book chapters (after Anna's Archive + LibGen)")
print()
print("Just use the GUI normally:")
print("  python main.py")
print()
print("Or try a book chapter:")
print("  10.1016/B978-0-443-27475-6.00019-X")
print()
print("Watch for these log lines:")
print("  ✓ [TELEGRAM] Success via Telegram Bots (@scihubot, etc.)")
print()
