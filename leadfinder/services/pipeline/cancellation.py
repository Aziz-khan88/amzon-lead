from __future__ import annotations

import threading
import time

from leadfinder.models import ResearchRun


class RunCanceled(Exception):
    """Raised when a background research run was canceled by the user."""


_lock = threading.Lock()
_checks: dict[str, tuple[float, bool]] = {}
# Hot pipeline loops poll this per query/result/page.  A sub-second memo window
# keeps those loops at zero extra DB queries while cancellation still lands
# within well under a second.
_MIN_INTERVAL_SECONDS = 0.75
_CACHE_CAP = 512


def raise_if_run_canceled(run_or_id) -> None:
    run_id = str(getattr(run_or_id, "id", run_or_id))
    now = time.monotonic()
    with _lock:
        entry = _checks.get(run_id)
    if entry is not None and now - entry[0] < _MIN_INTERVAL_SECONDS:
        if entry[1]:
            raise RunCanceled()
        return
    canceled = ResearchRun.objects.filter(id=run_id, status="canceled").exists()
    with _lock:
        if len(_checks) >= _CACHE_CAP:
            _checks.clear()
        _checks[run_id] = (now, canceled)
    if canceled:
        raise RunCanceled()
