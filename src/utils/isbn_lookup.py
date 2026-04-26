#!/usr/bin/env python3
"""
ISBN lookup and validation using multiple APIs.

Uses:
- Open Library API (best, free, no key needed)
- Google Books API (backup)
- ISBNdb (if API key available)
"""

import requests
from typing import Optional, Dict
import time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def validate_isbn(isbn: str) -> Optional[str]:
    """
    Validate and normalize ISBN.
    
    Returns:
        Normalized ISBN-13, or None if invalid
    """
    # Remove hyphens and spaces
    isbn = isbn.replace('-', '').replace(' ', '').upper()
    
    # Check if it's all digits (or X for ISBN-10)
    if not (isbn.replace('X', '').isdigit()):
        return None
    
    # ISBN-10 to ISBN-13 conversion
    if len(isbn) == 10:
        # Convert to ISBN-13
        isbn13 = '978' + isbn[:-1]
        
        # Calculate check digit
        check = 0
        for i, digit in enumerate(isbn13):
            check += int(digit) * (1 if i % 2 == 0 else 3)
        check_digit = (10 - (check % 10)) % 10
        
        return isbn13 + str(check_digit)
    
    elif len(isbn) == 13:
        # Validate ISBN-13 check digit
        check = 0
        for i, digit in enumerate(isbn[:-1]):
            check += int(digit) * (1 if i % 2 == 0 else 3)
        check_digit = (10 - (check % 10)) % 10
        
        if str(check_digit) == isbn[-1]:
            return isbn
        else:
            # Invalid check digit, but return anyway (might still work)
            return isbn
    
    return None


def lookup_isbn_openlibrary(isbn: str) -> Optional[Dict]:
    """
    Lookup ISBN using Open Library API (best, free, no key needed).
    
    Returns metadata: title, authors, publisher, year, etc.
    """
    try:
        url = f"https://openlibrary.org/api/books"
        params = {
            'bibkeys': f'ISBN:{isbn}',
            'format': 'json',
            'jscmd': 'data'
        }
        
        response = requests.get(url, params=params, headers={'User-Agent': UA}, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            book_key = f'ISBN:{isbn}'
            
            if book_key in data:
                book = data[book_key]
                
                # Extract metadata
                metadata = {
                    'title': book.get('title', ''),
                    'authors': [a.get('name', '') for a in book.get('authors', [])],
                    'publisher': book.get('publishers', [{}])[0].get('name', '') if book.get('publishers') else '',
                    'year': book.get('publish_date', ''),
                    'isbn': isbn,
                    'pages': book.get('number_of_pages'),
                    'cover': book.get('cover', {}).get('large', ''),
                    'source': 'openlibrary'
                }
                
                return metadata
    except Exception:
        pass
    
    return None


def lookup_isbn_google(isbn: str) -> Optional[Dict]:
    """
    Lookup ISBN using Google Books API (backup).
    """
    try:
        url = "https://www.googleapis.com/books/v1/volumes"
        params = {'q': f'isbn:{isbn}'}
        
        response = requests.get(url, params=params, headers={'User-Agent': UA}, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('totalItems', 0) > 0:
                book = data['items'][0]['volumeInfo']
                
                metadata = {
                    'title': book.get('title', ''),
                    'authors': book.get('authors', []),
                    'publisher': book.get('publisher', ''),
                    'year': book.get('publishedDate', ''),
                    'isbn': isbn,
                    'pages': book.get('pageCount'),
                    'cover': book.get('imageLinks', {}).get('thumbnail', ''),
                    'source': 'google_books'
                }
                
                return metadata
    except Exception:
        pass
    
    return None


def lookup_isbn(isbn: str) -> Optional[Dict]:
    """
    Lookup ISBN using multiple sources.
    
    Returns:
        Book metadata dict with title, authors, publisher, year, etc.
    """
    # Validate ISBN first
    normalized_isbn = validate_isbn(isbn)
    if not normalized_isbn:
        return None
    
    # Try Open Library first (best)
    metadata = lookup_isbn_openlibrary(normalized_isbn)
    if metadata:
        return metadata
    
    # Try Google Books as backup
    time.sleep(0.5)  # Rate limit
    metadata = lookup_isbn_google(normalized_isbn)
    if metadata:
        return metadata
    
    # If both fail, try original ISBN (might be ISBN-10)
    if isbn != normalized_isbn:
        metadata = lookup_isbn_openlibrary(isbn)
        if metadata:
            return metadata
        
        time.sleep(0.5)
        metadata = lookup_isbn_google(isbn)
        if metadata:
            return metadata
    
    return None


def format_book_metadata(metadata: Dict) -> str:
    """
    Format book metadata for display.
    """
    lines = []
    
    if metadata.get('title'):
        lines.append(f"Title: {metadata['title']}")
    
    if metadata.get('authors'):
        authors = ', '.join(metadata['authors'])
        lines.append(f"Authors: {authors}")
    
    if metadata.get('publisher'):
        lines.append(f"Publisher: {metadata['publisher']}")
    
    if metadata.get('year'):
        lines.append(f"Year: {metadata['year']}")
    
    if metadata.get('pages'):
        lines.append(f"Pages: {metadata['pages']}")
    
    if metadata.get('isbn'):
        lines.append(f"ISBN: {metadata['isbn']}")
    
    return '\n'.join(lines)


if __name__ == '__main__':
    # Test
    test_isbns = [
        '1803419490',  # User's test
        '0262035618',  # Deep Learning
        '978-0-262-03561-3',  # Deep Learning (with hyphens)
    ]
    
    for isbn in test_isbns:
        print(f"\n{'='*60}")
        print(f"Testing ISBN: {isbn}")
        print('='*60)
        
        metadata = lookup_isbn(isbn)
        if metadata:
            print(format_book_metadata(metadata))
        else:
            print("❌ Not found")
