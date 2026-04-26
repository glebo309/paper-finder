#!/usr/bin/env python3
"""
Enhanced arXiv API acquisition source.

Uses the official arXiv API instead of HTML scraping to find and download
PDFs for preprints that match the paper's title and/or DOI.

API docs: https://info.arxiv.org/help/api/index.html
"""

import re
from pathlib import Path
from typing import Dict, List
from xml.etree import ElementTree as ET

import requests

from src.core.base_source import SimpleAcquisitionSource


class ArxivAPISource(SimpleAcquisitionSource):
    """Acquire papers from arXiv via the official Atom API."""

    # Used by dynamic discovery to choose a default tier
    tier = "medium"

    @property
    def name(self) -> str:
        return "arXiv API"

    def get_download_urls(self, doi: str, metadata: Dict) -> List[str]:
        """Query arXiv API and return candidate PDF URLs.

        Strategy:
        1. Prefer title-based search using metadata["title"].
        2. Fallback: if DOI is present, include it in the query.
        3. Filter results by simple title similarity.
        4. Extract PDF links from Atom feed (link rel="related" or title="pdf").
        """
        urls: List[str] = []

        title = (metadata.get("title") or "").strip()
        if not title:
            return urls

        # Clean and shorten title for query
        clean_title = re.sub(r"\s+", " ", title)
        clean_title = clean_title.strip()[:200]

        # Build search query
        # Example: search_query=ti:"Quantum entanglement in ..."
        query_parts = [f'ti:"{clean_title}"']
        if doi:
            # Some arXiv records include DOI metadata; include it to improve ranking
            query_parts.append(f'all:"{doi}"')
        search_query = " AND ".join(query_parts)

        api_url = "http://export.arxiv.org/api/query"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": 5,
        }

        try:
            resp = self.session.get(api_url, params=params, timeout=15)
            if resp.status_code != 200:
                return urls

            # Parse Atom feed
            root = ET.fromstring(resp.content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns):
                entry_title_el = entry.find("atom:title", ns)
                entry_title = (entry_title_el.text or "") if entry_title_el is not None else ""

                if not self._titles_similar(title, entry_title):
                    continue

                # Extract PDF links
                for link in entry.findall("atom:link", ns):
                    href = link.get("href", "")
                    link_type = (link.get("type", "") or "").lower()
                    link_title = (link.get("title", "") or "").lower()

                    if not href:
                        continue

                    if "pdf" in link_type or link_title == "pdf" or "arxiv.org/pdf" in href:
                        if href not in urls:
                            urls.append(href)

                # Use only the first matching entry
                if urls:
                    break

        except Exception as e:
            print(f"  arXiv API error: {type(e).__name__}")

        return urls

    def _titles_similar(self, title1: str, title2: str, threshold: float = 0.6) -> bool:
        """Crude word-based similarity to avoid mismatches."""
        words1 = set(re.findall(r"\w+", title1.lower()))
        words2 = set(re.findall(r"\w+", title2.lower()))

        stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with"}
        words1 -= stop_words
        words2 -= stop_words

        if not words1 or not words2:
            return False

        intersection = len(words1 & words2)
        union = len(words1 | words2)
        similarity = intersection / union if union > 0 else 0.0
        return similarity >= threshold
