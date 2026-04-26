#!/usr/bin/env python3
"""
Book Finder - Specialized for finding books (not papers).

Uses:
- Anna's Archive (100M+ books)
- LibGen Books
- Z-Library
- Open Library
- Google Books
"""

from pathlib import Path
from typing import Optional
import sys

from src.acquisition.annas_archive import try_fetch_from_annas_archive
from src.acquisition.libgen import try_libgen_main


def find_book(
    title: str = None,
    isbn: str = None,
    author: str = None,
    output_dir: Path = None
) -> Optional[Path]:
    """
    Find and download a book.
    
    Args:
        title: Book title
        isbn: ISBN-10 or ISBN-13
        author: Author name
        output_dir: Where to save the book
    
    Returns:
        Path to downloaded book, or None if not found
    """
    if not title and not isbn:
        print("❌ Need at least a title or ISBN")
        return None
    
    if output_dir is None:
        output_dir = Path.home() / "Downloads"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create filename
    if title:
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_'))[:100]
        output_file = output_dir / f"{safe_title}.pdf"
    else:
        output_file = output_dir / f"book_{isbn}.pdf"
    
    print(f"\n📚 Searching for book...")
    if title:
        print(f"   Title: {title}")
    if isbn:
        print(f"   ISBN: {isbn}")
    if author:
        print(f"   Author: {author}")
    print()
    
    # Method 1: Anna's Archive (BEST for books!)
    print("🏴‍☠️ Trying Anna's Archive...")
    try:
        if try_fetch_from_annas_archive(doi=None, title=title, output_file=output_file, isbn=isbn):
            print(f"\n✅ Book downloaded: {output_file}")
            return output_file
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    # Method 2: LibGen Books
    print("\n📖 Trying LibGen Books...")
    try:
        authors = [author] if author else []
        if try_libgen_main(title, authors, output_file):
            print(f"\n✅ Book downloaded: {output_file}")
            return output_file
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    # Method 3: Telegram Bots (if enabled)
    print("\n🔥 Trying Telegram bots...")
    try:
        from src.core.config import get_config
        from src.acquisition.telegram_underground import TelegramUndergroundSource
        
        config = get_config()
        
        if config.telegram.underground_enabled and config.telegram.api_id:
            telegram_source = TelegramUndergroundSource(
                api_id=config.telegram.api_id,
                api_hash=config.telegram.api_hash,
                phone=config.telegram.phone,
                rate_limit_per_hour=config.telegram.rate_limit_per_hour
            )
            
            # Try with ISBN first, then title
            query = isbn if isbn else title
            print(f"   Querying Telegram bots with: {query[:60]}...")
            
            result = telegram_source.try_acquire(
                doi=query,  # Use ISBN or title as query
                output_file=output_file,
                metadata={'title': title, 'isbn': isbn, 'author': author}
            )
            
            if result.success:
                print(f"\n✅ Book downloaded via {result.source}: {output_file}")
                return output_file
            else:
                print(f"   ✗ Not found via Telegram bots")
        else:
            print("   ⚠ Telegram bots not enabled (run setup_telegram_underground.py)")
    except ImportError:
        print("   ⚠ Telethon not installed (pip install telethon)")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    print("\n❌ Book not found")
    return None


def main():
    """CLI for book finder"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Find and download books")
    parser.add_argument("--title", "-t", help="Book title")
    parser.add_argument("--isbn", "-i", help="ISBN-10 or ISBN-13")
    parser.add_argument("--author", "-a", help="Author name")
    parser.add_argument("--output", "-o", help="Output directory", type=Path)
    
    args = parser.parse_args()
    
    if not args.title and not args.isbn:
        # Interactive mode
        print("📚 Book Finder")
        print("=" * 50)
        title = input("Book title: ").strip()
        isbn = input("ISBN (optional): ").strip() or None
        author = input("Author (optional): ").strip() or None
        
        result = find_book(title=title, isbn=isbn, author=author, output_dir=args.output)
    else:
        result = find_book(
            title=args.title,
            isbn=args.isbn,
            author=args.author,
            output_dir=args.output
        )
    
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
