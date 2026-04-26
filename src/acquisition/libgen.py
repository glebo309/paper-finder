#!/usr/bin/env python3
"""
Library Genesis (LibGen) integration

LibGen is one of the largest repositories of books and papers.
Especially good for:
- Books and textbooks
- Older papers
- Non-English content
"""

import requests
from pathlib import Path
from typing import Optional
from bs4 import BeautifulSoup
import time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# LibGen mirrors (rotate if one fails)
LIBGEN_MIRRORS = [
    "http://libgen.rs",
    "http://libgen.is",
    "http://libgen.st",
]


def try_libgen_scimag(doi: str, output_file: Path) -> bool:
    """Try LibGen Scientific Articles (scimag) database."""
    try:
        print("    → LibGen (scimag)...")
        
        for mirror in LIBGEN_MIRRORS:
            try:
                # Search by DOI
                search_url = f"{mirror}/scimag/?q={doi}"
                response = requests.get(search_url, headers={'User-Agent': UA}, timeout=15)
                
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Find download links
                for row in soup.find_all('tr'):
                    # Look for download link
                    for link in row.find_all('a', href=True):
                        href = link['href']
                        
                        # LibGen download links
                        if 'get.php' in href or 'download' in href.lower():
                            download_url = href
                            if not download_url.startswith('http'):
                                download_url = f"{mirror}{href}"
                            
                            # Try to download
                            pdf_response = requests.get(
                                download_url, 
                                headers={'User-Agent': UA},
                                timeout=30,
                                allow_redirects=True
                            )
                            
                            # Check if PDF
                            if pdf_response.content.startswith(b'%PDF') and len(pdf_response.content) > 50*1024:
                                with output_file.open('wb') as f:
                                    f.write(pdf_response.content)
                                print(f"      ✓ Found on LibGen!")
                                return True
                
            except Exception as e:
                continue
        
        return False
        
    except Exception:
        return False


def try_libgen_main(title: str, authors: list, output_file: Path) -> bool:
    """Try LibGen main database (books)."""
    try:
        print("    → LibGen (books)...")
        
        # Build search query
        query = title
        if authors and len(authors) > 0:
            query = f"{authors[0]} {title}"
        
        for mirror in LIBGEN_MIRRORS:
            try:
                # Search
                search_url = f"{mirror}/search.php?req={query}&lg_topic=libgen&open=0&view=simple&res=25&phrase=1&column=def"
                response = requests.get(search_url, headers={'User-Agent': UA}, timeout=15)
                
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Find results table
                for row in soup.find_all('tr')[1:6]:  # Top 5 results
                    # Get title from row
                    title_cell = row.find('a', title=True)
                    if not title_cell:
                        continue
                    
                    result_title = title_cell.get_text().strip()
                    
                    # Check title similarity
                    from difflib import SequenceMatcher
                    similarity = SequenceMatcher(None, title.lower(), result_title.lower()).ratio()
                    
                    if similarity < 0.5:
                        continue
                    
                    # Find download link (usually in 'mirrors' column)
                    for link in row.find_all('a', href=True):
                        href = link['href']
                        if 'library.lol' in href or 'libgen.lc' in href or 'download' in href:
                            # Follow to get actual PDF
                            try:
                                dl_page = requests.get(href, headers={'User-Agent': UA}, timeout=15)
                                dl_soup = BeautifulSoup(dl_page.content, 'html.parser')
                                
                                # Find GET link
                                for dl_link in dl_soup.find_all('a', href=True):
                                    if 'get.php' in dl_link['href'] or 'download' in dl_link.get_text().lower():
                                        pdf_url = dl_link['href']
                                        if not pdf_url.startswith('http'):
                                            pdf_url = f"http://library.lol{pdf_url}"
                                        
                                        pdf_response = requests.get(pdf_url, timeout=30, allow_redirects=True)
                                        if pdf_response.content.startswith(b'%PDF') and len(pdf_response.content) > 50*1024:
                                            with output_file.open('wb') as f:
                                                f.write(pdf_response.content)
                                            print(f"      ✓ Found on LibGen (books)!")
                                            return True
                            except:
                                continue
                
            except Exception:
                continue
        
        return False
        
    except Exception:
        return False


def try_fetch_from_libgen(doi: str, title: str, authors: list, output_file: Path) -> Optional[str]:
    """
    Main entry point for LibGen.
    
    Tries both scimag (papers) and main (books) databases.
    """
    # Try scimag first (faster for papers with DOI)
    if doi and try_libgen_scimag(doi, output_file):
        return "libgen_scimag"
    
    # Try main database (books)
    if title and try_libgen_main(title, authors, output_file):
        return "libgen_books"
    
    return None
