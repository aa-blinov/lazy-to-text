"""CPU / RAM / GPU sampling, with no Qt.

``psutil`` for CPU and memory, ``nvidia-ml-py`` for the first NVIDIA GPU.
Used by the Qt topbar through :class:`app.resource_monitor.ResourceMonitor`
and by the Electron server, so neither has to know how the numbers are
read. GPU keys are present only when NVML answers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

log = logging.getLogger(__name__)


class ResourceSampler:
    def __init__(self) -> None:
        self._gpu_handle = None
        self._nvml_initialized = False

    def start(self) -> None:
        self._init_nvml()

    def stop(self) -> None:
        self._teardown_nvml()

    def sample(self) -> Dict[str, Any]:
        return self._collect()

    def _collect(self) -> Dict[str, Any]:
        try:
            import psutil  # type: ignore[import]
        except ImportError:
            return {}

        ram = psutil.virtual_memory()
        metrics: Dict[str, Any] = {
            # ``interval=None`` returns the average since the
            # previous call — first call returns 0.0, subsequent
            # calls give meaningful per-tick deltas.
            "cpu_percent": float(psutil.cpu_percent(interval=None)),
            "ram_used_mb": float(ram.used) / (1024 * 1024),
            "ram_total_mb": float(ram.total) / (1024 * 1024),
            "ram_percent": float(ram.percent),
        }

        if self._gpu_handle is not None:
            try:
                from pynvml import (  # type: ignore[import]
                    nvmlDeviceGetMemoryInfo,
                    nvmlDeviceGetUtilizationRates,
                )
                mem = nvmlDeviceGetMemoryInfo(self._gpu_handle)
                util = nvmlDeviceGetUtilizationRates(self._gpu_handle)
                metrics["gpu_vram_used_mb"] = float(mem.used) / (1024 * 1024)
                metrics["gpu_vram_total_mb"] = float(mem.total) / (1024 * 1024)
                metrics["gpu_util_percent"] = float(util.gpu)
            except Exception as exc:  # pragma: no cover — defensive
                log.debug("nvml sample failed, dropping GPU keys: %s", exc)

        return metrics

    def _init_nvml(self) -> None:
        if self._nvml_initialized:
            return
        try:
            from pynvml import (  # type: ignore[import]
                nvmlDeviceGetCount,
                nvmlDeviceGetHandleByIndex,
                nvmlInit,
            )
            nvmlInit()
            self._nvml_initialized = True
            if nvmlDeviceGetCount() > 0:
                self._gpu_handle = nvmlDeviceGetHandleByIndex(0)
                log.info("Resource monitor: NVML initialised, watching GPU 0")
            else:
                log.info("Resource monitor: NVML up but no GPUs reported")
        except Exception as exc:
            log.info(
                "Resource monitor: NVML unavailable, GPU metrics disabled: %s",
                exc,
            )

    def _teardown_nvml(self) -> None:
        if not self._nvml_initialized:
            return
        try:
            from pynvml import nvmlShutdown  # type: ignore[import]
            nvmlShutdown()
        except Exception:  # pragma: no cover — defensive
            pass
        self._nvml_initialized = False
        self._gpu_handle = None
