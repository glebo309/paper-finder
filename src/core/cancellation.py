"""Cooperative cancellation for acquisition HTTP and waits, without global patches.

A running socket read can finish up to its configured timeout. Cancellation
prevents the next request/redirect, retry wait, or streamed chunk from proceeding.
"""
from functools import wraps
import threading
import time

import requests

_local = threading.local()


class AcquisitionCancelled(BaseException):
    """Stop a losing source even when its legacy retry loop catches Exception."""


def _current_event():
    if hasattr(_local, 'stop'):
        return _local.stop
    from .pipeline import current_operation_stop_event
    return current_operation_stop_event()


def check_cancelled(event=None):
    event = event if event is not None else _current_event()
    if event is not None and event.is_set():
        raise AcquisitionCancelled('Acquisition stopped')


def cancellable_sleep(seconds):
    event = _current_event()
    check_cancelled(event)
    if event is None:
        time.sleep(seconds)
    elif event.wait(seconds):
        raise AcquisitionCancelled('Acquisition stopped')


def bind_cancellation(function):
    """Capture the caller's operation for a nested executor or thread callback."""
    event = _current_event()
    @wraps(function)
    def bound(*args, **kwargs):
        missing = object()
        previous = getattr(_local, 'stop', missing)
        _local.stop = event
        try:
            check_cancelled(event)
            return function(*args, **kwargs)
        finally:
            if previous is missing:
                del _local.stop
            else:
                _local.stop = previous
    return bound


class CancellableSession(requests.Session):
    """A session owns its creation event, or reads its caller's event per call."""
    def __init__(self):
        super().__init__()
        self._operation_event = _current_event()

    def _event(self):
        return self._operation_event if self._operation_event is not None else _current_event()

    def send(self, request, **kwargs):
        event = self._event()
        check_cancelled(event)
        response = super().send(request, **kwargs)
        try:
            check_cancelled(event)
        except AcquisitionCancelled:
            response.close()
            raise
        return response

    def request(self, method, url, **kwargs):
        event = self._event()
        check_cancelled(event)
        kwargs.setdefault('timeout', (5, 15))
        response = super().request(method, url, **kwargs)
        try:
            check_cancelled(event)
        except AcquisitionCancelled:
            response.close()
            raise
        if kwargs.get('stream'):
            original = response.iter_content
            def iter_content(*args, **stream_kwargs):
                iterator = iter(original(*args, **stream_kwargs))
                try:
                    while True:
                        check_cancelled(event)
                        try:
                            chunk = next(iterator)
                        except StopIteration:
                            return
                        check_cancelled(event)
                        yield chunk
                except AcquisitionCancelled:
                    response.close()
                    raise
            response.iter_content = iter_content
        return response


def request(method, url, **kwargs):
    with CancellableSession() as session:
        return session.request(method, url, **kwargs)


def get(url, **kwargs):
    return request('GET', url, **kwargs)


def post(url, **kwargs):
    return request('POST', url, **kwargs)
