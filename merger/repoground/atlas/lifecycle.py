"""
Atlas scan lifecycle executor.

Provides a shared try/except/finally pattern that guarantees every scan
reaches a terminal state ("complete" or "failed") regardless of which
entry-point (CLI or API) initiates the scan.

Status vocabulary
-----------------
Both paths use the same three status values:
  - ``"running"``  — scan is in progress
  - ``"complete"`` — scan finished successfully (terminal)
  - ``"failed"``   — scan terminated with an error (terminal)

Canonical truth model
---------------------
- **CLI path**: the SQLite AtlasRegistry is canonical for lifecycle and
  progress.  The ``snapshot_meta.json`` written on success is a result
  artifact, not a competing state source.
- **API path**: the JSON artifact file (``atlas-{id}.json``) is canonical
  because the API does not use the registry today.  Progress updates are
  written to the same file atomically.

The system thus has **path-specific asymmetric state backends**: the CLI
stores lifecycle state in SQLite, the API stores it in JSON files.  This
is a deliberate pragmatic trade-off — within each flow the state is
consistent, but a future consolidation (e.g. API adopting the registry)
would further reduce this asymmetry.

Both paths share identical *semantic* guarantees via this executor:
  1. Success  → status becomes ``"complete"``.
  2. Exception → status becomes ``"failed"`` **with** a persisted error text.
  3. Finally   → if status is still ``"running"`` (e.g. the except-handler
     itself raised), a zombie-guard forces ``"failed"``.

This module captures that shared guarantee as ``run_scan_lifecycle``.
"""

import logging
from typing import Callable

logger = logging.getLogger(__name__)


def run_scan_lifecycle(
    scan_fn: Callable[[], None],
    mark_failed: Callable[[str], None],
    is_still_running: Callable[[], bool],
    label: str = "atlas-scan",
) -> None:
    """Execute *scan_fn* with deterministic lifecycle guarantees.

    Parameters
    ----------
    scan_fn:
        The actual work — scanning, writing outputs, marking success.
        Must call its own "mark complete" logic internally on success.
    mark_failed:
        Called with an error message string when the scan must transition
        to "failed".  Implementations should be idempotent and never raise.
    is_still_running:
        Returns ``True`` when the snapshot/artifact is still in "running"
        state.  Used by the finally-guard to detect zombies.
    label:
        Human-readable identifier for log messages.
    """
    try:
        scan_fn()
    except Exception as exc:
        try:
            mark_failed(str(exc))
        except Exception:
            logger.warning("%s: mark_failed itself raised during exception handling", label, exc_info=True)
        raise
    finally:
        # Defensive zombie guard — if neither the success path inside
        # scan_fn nor the except handler above managed to move the state
        # out of "running", force it to "failed" now.
        try:
            if is_still_running():
                mark_failed("Scan finalization interrupted")
        except Exception:
            pass  # last-resort guard; nothing more we can do
