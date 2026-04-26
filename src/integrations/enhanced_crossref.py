#!/usr/bin/env python3
"""
Enhanced Crossref metadata extraction.

Extracts ALL possible links from Crossref metadata, including:
- Standard 'link' field
- 'resource' field (often overlooked!)
- 'relation' field (preprints, versions)
- 'assertion' field (supplementary material)
"""

import requests
from typing import List, Dict, Optional


def extract_all_crossref_links(doi: str, timeout: int = 10) -> List[str]:
    """
    Extract ALL possible links from Crossref metadata.
    
    This goes beyond the standard 'link' field to find hidden gems.
    """
    try:
        url = f"https://api.crossref.org/works/{doi}"
        response = requests.get(url, timeout=timeout)
        
        if response.status_code != 200:
            return []
        
        data = response.json().get('message', {})
        links = []
        
        # 1. Standard links (everyone checks these)
        for link in data.get('link', []):
            if link.get('URL'):
                links.append(('standard', link['URL'], link.get('content-type', 'unknown')))
        
        # 2. Resource links (OFTEN OVERLOOKED!)
        resource = data.get('resource', {})
        if resource:
            # Primary resource
            primary = resource.get('primary', {})
            if primary.get('URL'):
                links.append(('resource_primary', primary['URL'], 'primary'))
        
        # 3. Relation links (preprints, versions, etc.)
        relations = data.get('relation', {})
        for relation_type in ['is-preprint-of', 'has-preprint', 'is-version-of', 'has-version']:
            for item in relations.get(relation_type, []):
                if item.get('id'):
                    # This is a DOI of a related paper
                    related_doi = item['id']
                    links.append(('relation', f"https://doi.org/{related_doi}", relation_type))
                elif item.get('id-type') == 'doi' and item.get('id'):
                    links.append(('relation', f"https://doi.org/{item['id']}", relation_type))
        
        # 4. Assertion links (supplementary material, data, etc.)
        for assertion in data.get('assertion', []):
            if assertion.get('URL'):
                links.append(('assertion', assertion['URL'], assertion.get('label', 'unknown')))
        
        # 5. Archive locations (if paper is archived)
        archive = data.get('archive', [])
        for location in archive:
            if isinstance(location, str):
                # Sometimes it's just a string
                links.append(('archive', location, 'archive'))
        
        # Deduplicate while preserving order and metadata
        seen = set()
        unique_links = []
        for link_type, url, metadata in links:
            if url not in seen:
                seen.add(url)
                unique_links.append((link_type, url, metadata))
        
        return unique_links
    
    except Exception as e:
        print(f"  Enhanced Crossref extraction failed: {type(e).__name__}")
        return []


def get_crossref_metadata_enhanced(doi: str) -> Optional[Dict]:
    """
    Get enhanced Crossref metadata with additional fields.
    """
    try:
        url = f"https://api.crossref.org/works/{doi}"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            return None
        
        data = response.json().get('message', {})
        
        # Extract useful metadata
        meta = {
            'doi': doi,
            'title': data.get('title', [''])[0] if data.get('title') else '',
            'authors': [],
            'year': None,
            'journal': data.get('container-title', [''])[0] if data.get('container-title') else '',
            'publisher': data.get('publisher', ''),
            'type': data.get('type', ''),
            'is_oa': data.get('is-referenced-by-count', 0) > 0,  # Rough estimate
            'abstract': data.get('abstract', ''),
        }
        
        # Extract authors
        for author in data.get('author', []):
            if author.get('family'):
                name = f"{author.get('given', '')} {author.get('family', '')}".strip()
                meta['authors'].append(name)
        
        # Extract year
        published = data.get('published-print') or data.get('published-online') or data.get('created')
        if published and 'date-parts' in published:
            date_parts = published['date-parts'][0]
            if date_parts:
                meta['year'] = date_parts[0]
        
        # Extract ALL links
        meta['all_links'] = extract_all_crossref_links(doi)
        
        return meta
    
    except Exception as e:
        print(f"  Enhanced Crossref metadata failed: {type(e).__name__}")
        return None


def try_all_crossref_links(doi: str, output_file, session=None) -> bool:
    """
    Try ALL Crossref links, including hidden ones.
    
    Returns True if PDF found, False otherwise.
    """
    if session is None:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    links = extract_all_crossref_links(doi)
    
    if not links:
        return False
    
    print(f"  Found {len(links)} Crossref links (including hidden)")
    
    # Prioritize by type
    priority_order = ['resource_primary', 'standard', 'relation', 'assertion', 'archive']
    
    def get_priority(link):
        link_type = link[0]
        return priority_order.index(link_type) if link_type in priority_order else 999
    
    sorted_links = sorted(links, key=get_priority)
    
    for i, (link_type, url, metadata) in enumerate(sorted_links[:10], 1):  # Try top 10
        try:
            print(f"    [{i}] {link_type}: {url[:70]}...")
            
            response = session.get(url, timeout=30, allow_redirects=True)
            
            if response.status_code != 200:
                print(f"      ✗ HTTP {response.status_code}")
                continue
            
            # Check if PDF
            content_type = response.headers.get('content-type', '').lower()
            
            if 'pdf' in content_type or response.content.startswith(b'%PDF'):
                # Validate size
                if len(response.content) < 50*1024:
                    print(f"      ✗ Too small")
                    continue
                
                # Save
                with output_file.open('wb') as f:
                    f.write(response.content)
                
                print(f"      ✓ Found PDF via {link_type}!")
                return True
            else:
                print(f"      ✗ Not a PDF ({content_type})")
        
        except Exception as e:
            print(f"      ✗ Failed: {type(e).__name__}")
            continue
    
    return False
