"""Bring a browser-downloaded PDF back into a selected paper's workflow."""
from copy import deepcopy
from pathlib import Path
import os
import re
import tempfile
import uuid


def import_local_pdf(record, source_path, output_dir, max_size_mb=100, *, cancel_check=None):
    """Verify a private staging copy and publish only a matching document.

    No network access or acquisition engine is started. The original stays in
    place. A browser download alone does not establish its manuscript version.
    Optional cancel_check is consulted during staging and immediately before
    publication, so a cancelled verification never publishes its staged copy.
    """
    from paper_finder import DownloadResult
    from src.core.validation import verify_document_identity
    metadata = deepcopy(record)
    metadata.pop('fulltext_location', None)
    metadata.pop('imported_copy', None)
    source = Path(source_path).expanduser()
    destination = Path(output_dir).expanduser()
    temporary = None
    verification = None
    def cancelled():
        return bool(cancel_check is not None and cancel_check())
    def cancellation_result():
        return DownloadResult(False, source='Browser/local PDF', status='cancelled',
                              error='PDF import cancelled before publication; original file preserved.',
                              metadata=metadata, verification=verification)
    try:
        if cancelled():
            return cancellation_result()
        limit = int(float(max_size_mb) * 1024 * 1024)
        if limit <= 0 or not source.is_file():
            raise ValueError('Choose an existing PDF file within the size limit.')
        if source.stat().st_size > limit:
            raise ValueError('PDF exceeds the configured size limit.')
        destination.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.paperfinder-', suffix='.pdf', dir=destination)
        temporary = Path(name)
        size = 0
        with os.fdopen(fd, 'wb') as target, source.open('rb') as original:
            while chunk := original.read(65536):
                if cancelled():
                    return cancellation_result()
                size += len(chunk)
                if size > limit:
                    raise ValueError('PDF exceeds the configured size limit.')
                target.write(chunk)
        if cancelled():
            return cancellation_result()
        verification = verify_document_identity(temporary, metadata)
        if cancelled():
            return cancellation_result()
        status = verification['status']
        if status != 'verified':
            return DownloadResult(False, source='Browser/local PDF', status=status,
                metadata=metadata, verification=verification,
                error='; '.join(verification.get('reasons', [])))
        identity = (metadata.get('identifier') or {}).get('value') or metadata.get('doi') or 'paper'
        stem = re.sub(r'[^\w.\-]', '_', str(identity))[:140] or 'paper'
        output = destination / (stem + '.pdf')
        for attempt in range(5):
            try:
                if cancelled():
                    return cancellation_result()
                os.link(temporary, output)
                break
            except FileExistsError:
                output = destination / (stem + '_' + uuid.uuid4().hex[:10] + '.pdf')
        else:
            raise FileExistsError('Could not reserve a unique destination filename.')
        metadata['imported_copy'] = {'route': 'browser_or_local_file', 'version': 'unknown',
                                     'original_filename': source.name}
        return DownloadResult(True, source='Browser/local PDF', filepath=output,
                              status='verified', metadata=metadata, verification=verification)
    except (OSError, ValueError, TypeError) as exc:
        return DownloadResult(False, source='Browser/local PDF', status='error',
                              error=str(exc), metadata=metadata, verification=verification)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
