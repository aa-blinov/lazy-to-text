"""Background resource sampler for the topbar's live stats widget.

Polls CPU / RAM via ``psutil`` and GPU VRAM / utilisation via
``nvidia-ml-py`` on a Qt timer (so emissions land on the main
thread without an extra worker thread). Designed to be cheap —
``psutil.cpu_percent(interval=None)`` is non-blocking and
``nvmlDeviceGetMemoryInfo`` returns immediately from the driver.

The widget accepts a partial dict — keys are present only when the
corresponding subsystem is available (``gpu_*`` keys disappear on
machines with no NVIDIA driver).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from app.resource_sampler import ResourceSampler


log = logging.getLogger(__name__)

_DEFAULT_INTERVAL_MS = 2000


class ResourceMonitor(QObject):
    metrics_updated = Signal(dict)

    def __init__(
        self,
        interval_ms: int = _DEFAULT_INTERVAL_MS,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(max(500, int(interval_ms)))
        self._timer.timeout.connect(self._poll)

        self._sampler = ResourceSampler()

    # ---- public API ---------------------------------------------------------

    def start(self) -> None:
        self._init_nvml()
        # Fire one sample immediately so the UI doesn't show empty
        # values for the first ``interval_ms`` after boot.
        self._poll()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._teardown_nvml()

    def sample(self) -> Dict[str, Any]:
        """Public hook used by tests to read current values without
        spinning a Qt event loop."""
        return self._collect()

    # ---- internal -----------------------------------------------------------

    def _poll(self) -> None:
        try:
            metrics = self._collect()
        except Exception as exc:  # pragma: no cover — defensive
            log.debug("resource sample failed: %s", exc)
            return
        self.metrics_updated.emit(metrics)

    def _collect(self) -> Dict[str, Any]:
        return self._sampler._collect()

    def _init_nvml(self) -> None:
        self._sampler._init_nvml()

    def _teardown_nvml(self) -> None:
        self._sampler._teardown_nvml()

    @property
    def _gpu_handle(self):
        return self._sampler._gpu_handle
