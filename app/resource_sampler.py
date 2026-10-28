"""CPU and RAM sampling, with no UI imports."""

from typing import Any, Dict


class ResourceSampler:
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

        return metrics
