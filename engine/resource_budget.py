"""Conservative worker limits shared by CLI and the native application's jobs."""
from __future__ import annotations
import os


def worker_count(environ=None, processors=None, memory_bytes=None):
    env = os.environ if environ is None else environ
    cores = max(1, processors if processors is not None else (os.cpu_count() or 1))
    if memory_bytes is None:
        try:
            memory_bytes = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        except (ValueError, OSError, AttributeError):
            memory_bytes = 2 * 1024**3
    memory_limit = max(1, int(memory_bytes) // (2 * 1024**3))
    try:
        requested = int(env.get('PDF_WORKERS', min(4, max(1, cores - 1))))
    except (ValueError, TypeError):
        requested = 1
    return max(1, min(requested, cores, memory_limit, 8))
