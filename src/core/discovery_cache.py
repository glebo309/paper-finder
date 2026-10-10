"""Optional persistent cache for normalized scholarly metadata, never documents.

Cache failures are misses. Provider failures and empty searches are never cached,
so a newly indexed paper is not hidden behind an earlier negative result.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import parse_qsl, urlsplit


_SCHEMA_VERSION = 2
_FIELDS = frozenset(('identifier', 'doi', 'title', 'authors', 'year', 'journal',
    'abstract', 'metadata_source', 'sources', 'score', 'match_reasons', 'url',
    'pdf_urls', 'record_urls', 'arxiv_ids', 'preprint_years', 'cited_by_count',
    'metadata_warnings', 'record_type', 'is_retracted', 'publisher', 'source_ranks',
    'retrieval_score', 'pmid', 'pmcid', 'is_open_access', 'publication_date', 'related_doi', 'indexed_locations'))
_SECRET_PARAMS = frozenset(('api_key', 'apikey', 'key', 'token', 'access_token',
    'authorization', 'password', 'signature', 'sig', 'credential'))
_ERRORS = (OSError, sqlite3.Error, ValueError, TypeError, OverflowError)


def _default_directory():
    if os.environ.get('PAPER_FINDER_CACHE_DIR'):
        return Path(os.environ['PAPER_FINDER_CACHE_DIR']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Caches' / 'paper-finder'
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'paper-finder' / 'Cache'
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'paper-finder'


def _public_url(value):
    if not isinstance(value, str):
        return ''
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return ''
        for key, _ in parse_qsl(parsed.query):
            normalized = key.lower().replace('-', '_')
            if normalized in _SECRET_PARAMS or normalized.startswith(('x_amz_', 'x_goog_')):
                return ''
        return value
    except ValueError:
        return ''


def _records(value):
    if not isinstance(value, list) or not value:
        return None
    cleaned = []
    for record in value:
        if not isinstance(record, dict) or record.get('error') or 'errors' in record:
            return None
        if not isinstance(record.get('title'), str) or not record['title'].strip():
            return None
        identifier = record.get('identifier')
        if not isinstance(identifier, dict) or not all(isinstance(identifier.get(k), str) and identifier[k] for k in ('type', 'value')):
            return None
        item = {key: field for key, field in record.items() if key in _FIELDS}
        item['identifier'] = {key: identifier[key] for key in ('type', 'value')}
        if 'url' in item:
            item['url'] = _public_url(item['url'])
        for key in ('pdf_urls', 'record_urls'):
            if key in item:
                if not isinstance(item[key], list):
                    return None
                item[key] = [url for value in item[key] if (url := _public_url(value))]
        if 'indexed_locations' in item:
            if not isinstance(item['indexed_locations'], list):
                return None
            locations = []
            for location in item['indexed_locations']:
                if not isinstance(location, dict):
                    return None
                safe = {}
                for key in ('pdf_url', 'landing_page_url'):
                    if key in location:
                        safe[key] = _public_url(location[key]) or None
                for key in ('version', 'license', 'source'):
                    if key in location:
                        if location[key] is not None and not isinstance(location[key], str):
                            return None
                        safe[key] = location[key]
                for key in ('is_oa', 'requires_selection', 'downloadable', 'version_conflict'):
                    if key in location:
                        if location[key] is not None and not isinstance(location[key], bool):
                            return None
                        safe[key] = location[key]
                locations.append(safe)
            item['indexed_locations'] = locations
        cleaned.append(item)
    return cleaned


class DiscoveryCache:
    """Small SQLite cache shared by CLI invocations and desktop sessions.

    ``get`` returns records plus age/expiry, never stale data. ``put`` accepts
    successful normalized records only. Callers bypass get for explicit refresh.
    Operations use separate connections and short lock timeouts; cache contention
    never prevents discovery. Payload budgets bound retained data; SQLite reuses
    freed pages, with incremental vacuum reclaiming previously occupied pages.
    """

    def __init__(self, directory=None, *, enabled=None, ttl_seconds=86400,
                 max_entries=500, max_bytes=20 * 1024 * 1024,
                 max_entry_bytes=1024 * 1024, clock=time.time):
        self.path = (Path(directory).expanduser() if directory is not None else _default_directory()) / 'discovery-v1.sqlite3'
        self.enabled = (os.environ.get('PAPER_FINDER_CACHE', '1').strip().lower() not in ('0', 'false', 'off')
                        if enabled is None else bool(enabled))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.max_entries = max(0, int(max_entries))
        self.max_bytes = max(0, int(max_bytes))
        self.max_entry_bytes = max(0, int(max_entry_bytes))
        self.clock = clock

    @staticmethod
    def _key(provider, query, count, exact_doi):
        value = [_SCHEMA_VERSION, str(provider), ' '.join(str(query).split()), int(count), exact_doi]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

    @staticmethod
    def _provider(provider):
        key = str(provider).strip().lower()
        return 'openalex' if key.startswith('openalex_') else key

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=0.15)
        try:
            connection.execute('PRAGMA auto_vacuum=INCREMENTAL')
            connection.execute('CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, size INTEGER NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS cooldowns (provider TEXT PRIMARY KEY, deadline REAL NOT NULL)')
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, provider, query, count, exact_doi=None):
        if not self.enabled:
            return None
        try:
            key = self._key(provider, query, count, exact_doi)
            with self._connection() as connection:
                row = connection.execute('SELECT payload, created, expires FROM responses WHERE key=?', (key,)).fetchone()
                if row is None:
                    return None
                payload, created, expires = row
                now = self.clock()
                if expires <= now or created > now or len(payload.encode('utf-8')) > self.max_entry_bytes:
                    connection.execute('DELETE FROM responses WHERE key=?', (key,))
                    return None
                records = _records(json.loads(payload))
                if records is None:
                    connection.execute('DELETE FROM responses WHERE key=?', (key,))
                    return None
                return {'records': records, 'age_seconds': now - created, 'expires_at': expires}
        except _ERRORS:
            return None

    def put(self, provider, query, count, records, exact_doi=None):
        if not self.enabled or not self.max_entries or not self.max_bytes or self.ttl_seconds <= 0:
            return False
        try:
            normalized = _records(records)
            if normalized is None:
                return False
            payload = json.dumps(normalized, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            size = len(payload.encode('utf-8'))
            if size > min(self.max_entry_bytes, self.max_bytes):
                return False
            now = self.clock()
            if not math.isfinite(now + self.ttl_seconds):
                return False
            key = self._key(provider, query, count, exact_doi)
            with self._connection() as connection:
                # Acquire the writer lock before pruning or counting, including
                # when several processes complete responses simultaneously.
                connection.execute('BEGIN IMMEDIATE')
                connection.execute('DELETE FROM responses WHERE expires<=?', (now,))
                connection.execute('INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)',
                                   (key, payload, now, now + self.ttl_seconds, size))
                entries, total = connection.execute('SELECT COUNT(*), COALESCE(SUM(size), 0) FROM responses').fetchone()
                for old_key, old_size in connection.execute('SELECT key, size FROM responses ORDER BY created, rowid').fetchall():
                    if entries <= self.max_entries and total <= self.max_bytes:
                        break
                    connection.execute('DELETE FROM responses WHERE key=?', (old_key,))
                    entries -= 1
                    total -= old_size
                connection.execute('PRAGMA incremental_vacuum(32)')
            return True
        except _ERRORS:
            return False

    def cooldown_remaining(self, provider):
        if not self.enabled:
            return 0.0
        try:
            with self._connection() as connection:
                row = connection.execute('SELECT deadline FROM cooldowns WHERE provider=?', (self._provider(provider),)).fetchone()
                if row and math.isfinite(row[0]):
                    return max(0.0, row[0] - self.clock())
        except _ERRORS:
            pass
        return 0.0

    def set_cooldown(self, provider, seconds):
        if not self.enabled:
            return False
        try:
            seconds = float(seconds)
            if not math.isfinite(seconds) or seconds <= 0:
                return False
            now = self.clock()
            with self._connection() as connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute('DELETE FROM cooldowns WHERE deadline<=?', (now,))
                connection.execute('INSERT INTO cooldowns VALUES (?, ?) ON CONFLICT(provider) DO UPDATE SET deadline=MAX(deadline, excluded.deadline)',
                                   (self._provider(provider), now + seconds))
            return True
        except _ERRORS:
            return False
