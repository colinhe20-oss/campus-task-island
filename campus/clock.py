"""Context-local business clock; authentication/session expiry stays on real time."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

_clock = ContextVar('campus_business_clock', default=None)


def utc_now():
    clock = _clock.get()
    value = clock() if clock else datetime.now(timezone.utc)
    if value.utcoffset() is None:
        raise ValueError('业务时钟必须带时区')
    return value.astimezone(timezone.utc)


@contextmanager
def business_time(clock):
    token = _clock.set(clock)
    try:
        yield
    finally:
        _clock.reset(token)
