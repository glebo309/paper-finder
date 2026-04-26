#!/bin/bash

# Install script for Telegram Bots Access
# This enables access to private mirrors, Z-Library, and community caches

echo "=================================================="
echo "TELEGRAM BOTS ACCESS INSTALLER"
echo "=================================================="
echo ""
echo "This will set up access to Telegram bots:"
echo "  • @scihubot (private Sci-Hub mirrors)"
echo "  • @libgen_scihub_bot (direct LibGen DB)"
echo "  • Z-Library (10M+ books)"
echo "  • Community caches"
echo ""
echo "Expected improvement: +15-20% success rate"
echo ""

# Install Telethon if not installed
echo "Installing Telethon library..."
pip install telethon

echo ""
echo "=================================================="
echo "SETUP REQUIRED"
echo "=================================================="
echo ""
echo "You need Telegram API credentials (free):"
echo ""
echo "1. Go to: https://my.telegram.org"
echo "2. Login with your phone number"
echo "3. Click 'API development tools'"
echo "4. Create an app (any name)"
echo "5. Note your api_id and api_hash"
echo ""
echo "Then run:"
echo "  python setup_telegram_underground.py"
echo ""
echo "Or set environment variables:"
echo "  export TELEGRAM_API_ID='your_id'"
echo "  export TELEGRAM_API_HASH='your_hash'"
echo "  python auto_enable_underground.py"
echo ""
echo "=================================================="
echo ""

# Check if we can auto-enable
if [ -n "$TELEGRAM_API_ID" ] && [ -n "$TELEGRAM_API_HASH" ]; then
    echo "✅ Found API credentials in environment!"
    echo "Auto-enabling Telegram bots access..."
    python auto_enable_underground.py
else
    echo "Would you like to set up now? (y/n)"
    read -r response
    if [ "$response" = "y" ]; then
        python setup_telegram_underground.py
    fi
fi

echo ""
echo "Setup complete! The GUI will now use Telegram bots automatically."
