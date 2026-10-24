// Figures and labels of the status strip, as plain functions.

export const ACCELERATORS = ['CUDA', 'CoreML', 'TensorRT', 'DirectML', 'ROCm', 'Azure'];

/** A byte count, in the largest unit that keeps it readable. */
export function formatBytes(n) {
  if (!(n > 0)) return '';
  let value = n;
  for (const unit of ['B', 'KB', 'MB', 'GB']) {
    if (value < 1024) return unit === 'B' ? `${value.toFixed(0)} B` : `${value.toFixed(1)} ${unit}`;
    value /= 1024;
  }
  return `${value.toFixed(1)} TB`;
}

/** Whole percent of a download, capped at 99 until the load really ends. */
export function percent(current, total) {
  if (!(total > 0) || !(current >= 0)) return null;
  return Math.min(99, Math.max(0, Math.floor((current * 100) / total)));
}

/**
 * The loading line: progress with bytes when a size is known, bytes alone
 * when it is not, and the elapsed seconds when no download is reporting
 * (a cached model being read).
 */
export function loadingDetail({ current = 0, total = 0, elapsed = 0 } = {}) {
  const pct = percent(current, total);
  const parts = [];
  if (pct !== null) parts.push(`${formatBytes(current)} / ${formatBytes(total)} (${pct}%)`);
  else if (current > 0) parts.push(formatBytes(current));
  if (elapsed > 0) parts.push(`${elapsed} s`);
  return parts.join(' · ');
}

export function isAccelerator(provider) {
  return ACCELERATORS.includes(provider);
}

/** Resource figures the strip shows, in order, or [] before the first sample. */
export function resourceItems(r = {}) {
  const items = [];
  if (typeof r.cpu_percent === 'number') items.push({ key: 'CPU', value: `${Math.round(r.cpu_percent)}%`, percent: r.cpu_percent });
  if (typeof r.ram_percent === 'number') {
    const used = (r.ram_used_mb ?? 0) / 1024;
    const total = (r.ram_total_mb ?? 0) / 1024;
    items.push({ key: 'RAM', value: total ? `${used.toFixed(1)}/${total.toFixed(1)} GB` : `${Math.round(r.ram_percent)}%`, percent: r.ram_percent });
  }
  if (typeof r.gpu_util_percent === 'number') items.push({ key: 'GPU', value: `${Math.round(r.gpu_util_percent)}%`, percent: r.gpu_util_percent });
  if (r.gpu_vram_total_mb) {
    const used = (r.gpu_vram_used_mb ?? 0) / 1024;
    const total = r.gpu_vram_total_mb / 1024;
    items.push({ key: 'VRAM', value: `${used.toFixed(1)}/${total.toFixed(1)} GB`, percent: (100 * (r.gpu_vram_used_mb ?? 0)) / r.gpu_vram_total_mb });
  }
  return items;
}

/** Tone of a load figure: calm, busy, saturated. */
export function loadTone(percentValue) {
  if (percentValue >= 85) return 'text-danger-text';
  if (percentValue >= 50) return 'text-warning-text';
  return 'text-ink-soft';
}
