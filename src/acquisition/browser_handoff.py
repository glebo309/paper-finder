"""Watch a user-chosen download folder, then verify new PDFs entirely offline."""
from copy import deepcopy
import math
import os
from pathlib import Path
import stat
import threading
import time

from .local_import import import_local_pdf


class BrowserDownloadWatcher:
    """Polling state machine with bounded work and no background activity.

    Existing unchanged files are ignored. Candidates must be regular, nonsymlink
    PDFs with the same fingerprint on two polls. Browser originals are preserved.
    Call ``poll`` about once per second; cancellation is checked between files.
    """
    MAX_DIRECTORY_ENTRIES = 10000
    MAX_CANDIDATES_PER_POLL = 20

    def __init__(self, record, download_dir, output_dir, timeout=300, *, clock=time.monotonic, max_size_mb=100):
        self.record = deepcopy(record)
        self.download_dir = Path(download_dir).expanduser()
        self.output_dir = Path(output_dir).expanduser()
        self.clock = clock
        self.started = clock()
        self.timeout = float(timeout)
        self.max_bytes = int(float(max_size_mb) * 1024 * 1024)
        self.status = 'waiting'
        self.message = 'Waiting for a new browser PDF download.'
        self._cancelled = threading.Event()
        self._result = None
        self._seen = {}
        self._attempted = {}
        self._initial = {}
        try:
            if not math.isfinite(self.timeout) or self.timeout <= 0 or self.max_bytes <= 0:
                raise ValueError('Choose a positive finite timeout and size limit.')
            self._initial = self._scan()
        except (OSError, ValueError) as exc:
            self._finish('error', f'Cannot watch download folder: {exc}')

    @property
    def finished(self):
        return self._result is not None

    def _finish(self, status, message):
        from paper_finder import DownloadResult
        self.status, self.message = status, message
        self._result = DownloadResult(False, source='Browser download watcher', status=status,
                                      error=message, metadata=deepcopy(self.record))
        return self._result

    def _scan(self):
        if not self.download_dir.is_dir() or self.download_dir.is_symlink():
            raise ValueError('Choose an existing download folder, not a symlink.')
        result = {}
        with os.scandir(self.download_dir) as entries:
            for index, entry in enumerate(entries):
                if index >= self.MAX_DIRECTORY_ENTRIES:
                    raise ValueError('Download folder is too large; choose a folder with fewer than 10,000 entries.')
                path = Path(entry.path)
                if path.name.startswith('.') or path.suffix.lower() != '.pdf':
                    continue
                if any(suffix.lower() in ('.crdownload', '.download', '.part', '.tmp') for suffix in path.suffixes):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    continue
                result[path] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        return result

    def cancel(self):
        self._cancelled.set()

    def poll(self):
        if self.finished:
            return self._result
        if self._cancelled.is_set():
            return self._finish('cancelled', 'Browser download watch cancelled; original files were preserved.')
        if self.clock() - self.started >= self.timeout:
            return self._finish('timeout', 'No matching stable PDF arrived before the timeout. You can restart watching or import a PDF manually.')
        try:
            current = self._scan()
        except (OSError, ValueError) as exc:
            return self._finish('error', f'Cannot read download folder: {exc}')
        candidates = [(path, fingerprint) for path, fingerprint in current.items()
                      if fingerprint != self._initial.get(path) and fingerprint != self._attempted.get(path)
                      and 0 < fingerprint[2] <= self.max_bytes]
        previous, self._seen = self._seen, {path: fp for path, fp in candidates}
        attempted = 0
        for path, fingerprint in candidates:
            if self._cancelled.is_set():
                return self._finish('cancelled', 'Browser download watch cancelled; original files were preserved.')
            if self.clock() - self.started >= self.timeout:
                return self._finish('timeout', 'Browser download watch timed out; original files were preserved.')
            if previous.get(path) != fingerprint:
                continue
            if attempted >= self.MAX_CANDIDATES_PER_POLL:
                break
            # Recheck the file immediately before passing it to the importer.
            try:
                info = path.lstat()
                latest = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                if not stat.S_ISREG(info.st_mode) or latest != fingerprint:
                    continue
            except OSError:
                continue
            attempted += 1
            self._attempted[path] = fingerprint
            try:
                result = import_local_pdf(self.record, path, self.output_dir, max_size_mb=self.max_bytes / 1024 / 1024,
                    cancel_check=lambda: self._cancelled.is_set() or self.clock() - self.started >= self.timeout)
            except Exception:
                if self._cancelled.is_set():
                    return self._finish('cancelled', 'Browser download watch cancelled; original files were preserved.')
                if self.clock() - self.started >= self.timeout:
                    return self._finish('timeout', 'Browser download watch timed out; original files were preserved.')
                self.message = f'Could not inspect {path.name}; still waiting for a matching PDF.'
                continue
            if self._cancelled.is_set():
                return self._finish('cancelled', 'Browser download watch cancelled; original files were preserved.')
            if self.clock() - self.started >= self.timeout:
                return self._finish('timeout', 'Browser download watch timed out; original files were preserved.')
            if result.success and result.status == 'verified':
                self._result = result
                self.status = 'verified'
                self.message = f'Verified and imported {path.name}; the original download was preserved.'
                return result
            self.message = f'Ignored {path.name}: {result.status}. Still waiting for a matching PDF.'
        # Forget attempts for files no longer present to keep memory bounded.
        self._attempted = {path: fp for path, fp in self._attempted.items() if path in current}
        return None
