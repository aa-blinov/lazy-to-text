# Parity: capsule and status strip (Qt overlay, topbar, status chip vs `Overlay.svelte`, `StatusStrip.svelte`)

Reference: `app/gui/widgets/recording_overlay.py`, `recording_status_widget.py`,
`vu_meter.py`, `topbar.py`, `resource_widget.py`, specs 001 and 007. Renderer:
`Overlay.svelte`, `components/capsule/copy.js`, `components/LevelMeter.svelte`,
`components/StatusStrip.svelte`, `components/statusFormat.js`. The capsule's
window, visibility and placement stay in `desktop/electron/windows.cjs`.

## Capsule

| Qt state or message | Electron |
| --- | --- |
| `recording`: title "Recording", body "Speak now", dot in the recording colour | Same strings; dot `bg-danger`, pulsing unless the user prefers reduced motion |
| `processing`: "Processing" / "Transcribing speech"; no move or hide between recording and processing | Same strings; the state goes recording to processing without idle, and the window rule in `windows.cjs` keeps it up and in place |
| `pasted`: title "Paste sent" (never "Pasted"), body the text collapsed to one line | Same (`capsuleCopy`), tested |
| `copied`: "Copied — press <shortcut>", or "Copied" without one; body the text, or "Copied to clipboard" when empty | Same |
| `failed`: "Delivery failed", body "Nothing was pasted. The reason is in Logs."; the text is not shown | Same; tested that the copy never carries the text |
| Unknown outcome ignored | Same |
| Confirmation survives `idle` for a fixed time | The page keeps the confirmation for 3 s after it arrives; the window hides at its own 2.6 s from the same event |
| A new recording cancels the confirmation | Same: entering `recording` or `processing` drops it |
| Body cut with an ellipsis at a width cap | CSS truncation at `max-w-md` |
| Fixed height in every state | One height (`h-14`) in every state |
| Accessible name carrying the state | `role="status"` with the title and body as its text and the name "Recording status"; the level meter is a `meter` named "Microphone level" |
| Language switch re-renders the copy | Reactive on the shared language store |
| (not in Qt capsule) | **Added:** elapsed recording time (mm:ss) and a live level meter from the `level` event, in the capsule while recording |

## Status strip

| Qt element | Electron |
| --- | --- |
| Sidebar chip: state pill "Idle", "Recording", "Processing", "Loading model…" | `Badge` with a dot in the strip; same words; tone by state |
| No ONNX Runtime execution-provider pill | No ONNX Runtime execution-provider pill |
| Topbar model pill "Current model: %1" / "No model" | Same strings |
| Topbar loading pill "Loading: %1" with percent, else bytes, else elapsed seconds, and a Cancel button | Progress bar (determinate when a size is known, else indeterminate), "bytes / total (percent) · elapsed s", and Cancel calling `models.cancel_load`; an `unknown_method` reply (the method not yet there) is reported in a toast, never swallowed |
| CPU and RAM usage, shown once a model exists | Shown whenever a resource sample exists; coloured by load; hidden below the `md` breakpoint |
| VU meter along the chip while recording, peak and decay, green below half, warning to 0.85, danger above | `LevelMeter` in the strip while recording with the same thresholds and a decay of 0.85 per update |
| (not in Qt) | **Added:** the strip is persistent on every screen; the sidebar footer that repeated state and model was removed |

## Shell

- Cmd/Ctrl+1..6 select the screens in sidebar order (FR-012), in `App.svelte`;
  other modifiers and unbound digits are left alone.

## Differences and gaps

- The capsule sits in the bottom-right corner of the work area of the display under the
  pointer, as the Qt capsule does (spec 007, FR-007); see parity-audit.md, M8.
- The capsule and strip were drawn in a browser tab against a fake event source,
  in dark and light; they were not run inside Electron here.
