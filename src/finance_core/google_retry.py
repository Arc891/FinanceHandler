"""
Bounded retry for idempotent Google calls (plan 4.4, "Retry scope").

Wrap reads, resolves, ``files.*`` and ``spreadsheets.create``/``copyTo`` only.
**Never wrap a values update.** It is not idempotent: a 5xx or a dropped
connection after the mutation landed would append the block a second time
while reporting success. Write failures are reconciled instead (plan 4.6).
"""

import logging
import time

logger = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
DELAYS = (5, 15, 45)


def status_of(exc):
    """The HTTP status of a gspread APIError or googleapiclient HttpError, else None."""
    response = getattr(exc, "response", None)          # gspread.exceptions.APIError
    status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "resp", None), "status", None)   # HttpError
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def with_retry(fn, *, delays=DELAYS, sleep=time.sleep, what="Google call"):
    """Call ``fn()``; on 429/5xx retry once per entry in ``delays``, sleeping that long first."""
    for attempt, delay in enumerate((*delays, None)):
        try:
            return fn()
        except Exception as exc:
            status = status_of(exc)
            if delay is None or status not in RETRY_STATUSES:
                raise
            logger.warning("%s failed with HTTP %s; retry %d/%d in %ss",
                           what, status, attempt + 1, len(delays), delay)
            sleep(delay)
