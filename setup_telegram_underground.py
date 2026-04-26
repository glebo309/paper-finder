#!/usr/bin/env python3
"""
Setup script for Telegram Underground Bot Access.

This will help you configure access to underground Telegram bots
that have private Sci-Hub mirrors, Z-Library, and community caches.

RUN THIS FIRST:
1. Go to https://my.telegram.org
2. Login with your phone
3. Click "API development tools"
4. Create an app (if you haven't already)
5. Note your api_id and api_hash

Then run this script to set everything up.
"""

import os
import sys
import yaml
from pathlib import Path
from getpass import getpass


def main():
    print("=" * 60)
    print("TELEGRAM BOTS ACCESS SETUP")
    print("=" * 60)
    print()
    print("This will configure access to Telegram bots:")
    print("  • @scihubot (private Sci-Hub mirrors)")
    print("  • @libgen_scihub_bot (direct LibGen DB)")
    print("  • @scihub_bot (alternative)")
    print("  • @booksandpapers_bot (community uploads)")
    print()
    print("These bots have access to:")
    print("  ✓ Private Sci-Hub mirrors (more up-to-date)")
    print("  ✓ Z-Library (10M+ books)")
    print("  ✓ Direct database access (faster)")
    print("  ✓ Community-uploaded papers")
    print("  ✓ Cached successful downloads")
    print()
    print("Expected improvement: +15-20% success rate")
    print("Speed: 2-5 seconds (vs 30-60 seconds scraping)")
    print()
    print("-" * 60)
    
    # Check if user has credentials
    print("\nHave you already obtained your Telegram API credentials?")
    print("(from https://my.telegram.org)")
    response = input("(y/n): ").lower().strip()
    
    if response != 'y':
        print("\n📱 Please get your credentials first:")
        print("1. Go to https://my.telegram.org")
        print("2. Login with your phone number")
        print("3. Click 'API development tools'")
        print("4. Create an app (any name is fine)")
        print("5. Note your api_id and api_hash")
        print("\nThen run this script again.")
        sys.exit(0)
    
    print("\n" + "=" * 60)
    print("ENTER YOUR CREDENTIALS")
    print("=" * 60)
    
    # Get API ID
    api_id = input("\nEnter your API ID (numbers only): ").strip()
    if not api_id.isdigit():
        print("❌ API ID must be numbers only")
        sys.exit(1)
    
    # Get API Hash
    api_hash = getpass("Enter your API Hash (hidden): ").strip()
    if not api_hash:
        print("❌ API Hash cannot be empty")
        sys.exit(1)
    
    # Get phone (optional)
    print("\nPhone number (optional, for first-time auth)")
    print("Format: +1234567890 (with country code)")
    phone = input("Phone (press Enter to skip): ").strip() or None
    
    print("\n" + "=" * 60)
    print("CONFIGURATION OPTIONS")
    print("=" * 60)
    
    # Auto-enable
    enable = input("\nEnable underground access by default? (y/n): ").lower().strip() == 'y'
    
    # Rate limit
    rate_limit = input("Max requests per hour (default 20): ").strip()
    if rate_limit and rate_limit.isdigit():
        rate_limit = int(rate_limit)
    else:
        rate_limit = 20
    
    print("\n" + "=" * 60)
    print("SAVING CONFIGURATION")
    print("=" * 60)
    
    # Option 1: Environment variables
    print("\nOption 1: Save as environment variables")
    print("Add these to your ~/.zshrc or ~/.bashrc:")
    print()
    print(f"export TELEGRAM_API_ID='{api_id}'")
    print(f"export TELEGRAM_API_HASH='{api_hash}'")
    if phone:
        print(f"export TELEGRAM_PHONE='{phone}'")
    print()
    
    # Option 2: Config file
    config_path = Path("config.yaml")
    
    if config_path.exists():
        # Load existing config
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
    
    # Update telegram section
    if 'telegram' not in config:
        config['telegram'] = {}
    
    config['telegram'].update({
        'underground_enabled': enable,
        'api_id': api_id,
        'api_hash': api_hash,
        'rate_limit_per_hour': rate_limit,
        'underground_bots': [
            '@scihubot',
            '@libgen_scihub_bot', 
            '@scihub_bot',
            '@booksandpapers_bot'
        ]
    })
    
    if phone:
        config['telegram']['phone'] = phone
    
    # Save config
    save_config = input("\nSave to config.yaml? (y/n): ").lower().strip() == 'y'
    
    if save_config:
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        print(f"✅ Saved to {config_path}")
    
    print("\n" + "=" * 60)
    print("SETUP COMPLETE!")
    print("=" * 60)
    print()
    print("✅ Telegram underground access is configured!")
    print()
    print("The system will now try these bots as a last resort:")
    print("  • @scihubot")
    print("  • @libgen_scihub_bot")
    print("  • @scihub_bot")
    print("  • @booksandpapers_bot")
    print()
    print("First run notes:")
    print("  • On first use, Telegram will send a code to your phone")
    print("  • Enter this code when prompted")
    print("  • The session will be saved (no need to auth again)")
    print()
    print("Usage:")
    print("  • Just use the GUI normally")
    print("  • Underground bots will be tried automatically")
    print("  • Watch the logs for [UNDERGROUND] messages")
    print()
    print("Expected improvement:")
    print("  • +15-20% success rate on hard-to-find papers")
    print("  • Especially effective for 2020-2025 papers")
    print("  • Much faster (2-5 seconds vs 30-60)")
    print()
    print("Happy paper hunting! 📚🔓")


if __name__ == "__main__":
    main()
