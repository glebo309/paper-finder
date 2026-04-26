#!/usr/bin/env python3
"""
Telegram Authentication Script.
Run this ONCE interactively to authenticate your session.
"""

import sys
import os
import logging
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper_finder import PaperFinder
from telethon import TelegramClient

# Configure logging
logging.basicConfig(level=logging.INFO)

def auth_telegram():
    print("="*60)
    print("TELEGRAM AUTHENTICATION")
    print("="*60)
    
    # Initialize PaperFinder to load config
    try:
        finder = PaperFinder()
    except Exception as e:
        print(f"Failed to initialize PaperFinder: {e}")
        return

    if not finder.config or not hasattr(finder.config, 'telegram'):
        print("❌ Telegram config missing")
        return
    
    api_id = finder.config.telegram.api_id
    api_hash = finder.config.telegram.api_hash
    phone = finder.config.telegram.phone
    
    if not api_id or not api_hash:
        print("❌ API ID or Hash missing in config.yaml")
        return

    print(f"API ID: {api_id}")
    print(f"Phone: {phone}")
    print("\nConnecting to Telegram...")
    
    session_name = 'paper_finder_telegram_session'
    client = TelegramClient(session_name, api_id, api_hash)
    
    async def main():
        # This will prompt for code if not authenticated
        await client.start(phone=phone)
        print("\n✅ Authentication successful!")
        print(f"Session saved to: {session_name}.session")
        print("You can now run the benchmark without login prompts.")
        
        # Send a test message to Saved Messages to confirm
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} (@{me.username})")

    import asyncio
    client.loop.run_until_complete(main())

if __name__ == "__main__":
    auth_telegram()
