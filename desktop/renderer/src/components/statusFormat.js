// Figures and labels of the status strip, as plain functions.

import { tr, formatNumber } from '../lib/i18n.js';

export const ACCELERATORS = ['CUDA', 'CoreML', 'TensorRT', 'DirectML', 'ROCm', 'Azure'];

/** A byte count, in the largest unit that keeps it readable. */
export function formatBytes(n) {
  if (!(n > 0)) return '';
  let value = n;
  for (const unit of ['B', 'KB', 'MB', 'GB']) {
    if (value < 1024) return unit === 'B' ? `${formatNumber(value, 0)} ${tr('B')}` : `${formatNumber(value, 1)} ${tr(unit)}`;
    value /= 1024;
  }
  return `${formatNumber(value, 1)} TB`;
}

/**
 * Whole percent of a download, rounded and capped at 99 until the load really
 * ends. The one place the number is made: the status strip, the Models banner
 * and card, and the first-run screen all read it, so they cannot disagree.
 */
export function percent(current, total) {
  if (!(total > 0) || !(current >= 0)) return null;
  return Math.min(99, Math.max(0, Math.round((current * 100) / total)));
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
  if (elapsed > 0) parts.push(tr('%1 s').replace('%1', String(elapsed)));
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
    items.push({ key: 'RAM', value: total ? `${formatNumber(used, 1)}/${formatNumber(total, 1)} ${tr('GB')}` : `${Math.round(r.ram_percent)}%`, percent: r.ram_percent });
  }
  if (typeof r.gpu_util_percent === 'number') items.push({ key: 'GPU', value: `${Math.round(r.gpu_util_percent)}%`, percent: r.gpu_util_percent });
  if (r.gpu_vram_total_mb) {
    const used = (r.gpu_vram_used_mb ?? 0) / 1024;
    const total = r.gpu_vram_total_mb / 1024;
    items.push({ key: 'VRAM', value: `${formatNumber(used, 1)}/${formatNumber(total, 1)} ${tr('GB')}`, percent: (100 * (r.gpu_vram_used_mb ?? 0)) / r.gpu_vram_total_mb });
  }
  return items;
}

/** Tone of a load figure: calm, busy, saturated. */
export function loadTone(percentValue) {
  if (percentValue >= 85) return 'text-danger-text';
  if (percentValue >= 50) return 'text-warning-text';
  return 'text-ink-soft';
}
