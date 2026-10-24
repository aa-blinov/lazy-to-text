# Feature Specification: Remove the Qt Interface and the CUDA Build

**Feature Branch**: `aa-blinov/llm-reasoning-tokens-config-624055`

**Created**: 2026-10-24

**Status**: Implemented (uncommitted, awaiting review)

**Input**: "Delete the Qt interface and ship only the Electron interface. Drop CUDA/GPU support entirely: CPU everywhere, CoreML on Apple silicon through the stock onnxruntime."

## Why

Spec 010 gave the application a second front end on the same engine. Two front ends doubled every behaviour change, kept PySide6 (about 80 MB of the macOS bundle, a second theme system, a second translation catalogue) in the dependency set, and kept two release pipelines racing for one GitHub release. The team decided that Electron is the product. The CUDA build existed only as a Windows variant of the Qt bundle and an auto-installer of NVIDIA wheels; it goes with it.

## What is removed

- The Qt interface: `app/gui/**`, `app/language.py`, `app/resource_monitor.py`, the Qt translation catalogue (`app/i18n/app_ru.ts`, `.qm`), the Qt entry point `lazy-to-text-ui.py` and the console scripts `lazy-to-text-ui` and `lazy-to-text-ui-cuda`.
- The Qt packaging chain: `setup.py` (py2app), `lazy_to_text.spec`, `installer/` (Inno Setup), `scripts/build-macos.sh`, `build-windows.ps1`, `build-windows-cuda.ps1`, `setup-cuda-windows.ps1`, `prune_bundle.py`, the Qt screenshot and icon generators.
- CUDA: `app/cuda_bootstrap.py`, its call in the runtime entry, the NVIDIA wheel logic, the CUDA release artifact.
- Qt tests: `tests/gui/**`, `tests/test_bundle_contents.py`, `tests/test_resource_monitor.py`, `tests/test_cuda_bootstrap.py`, the Qt test of the overlay anchor.
- Dependencies: `pyside6`, `pytest-qt`, `py2app`.
- Release workflow jobs that built and published the Qt artifacts.

## What is kept and moved

The engine, the Python runtime (`app/server`), every Qt-free module (`hotkey_rules`, `mic_test`, `ui_prefs`, `audio_formats`, `translation_mark`, `resource_sampler`, `bootstrap`, `system_audio`, `macos_*`, `instance_manager`, `macos_permissions`), `vendor/portaudio`, the sounds, the signing scripts, `scripts/build_server.py` and the Electron chain.

Moved because the live runtime imported them from `app/gui`:

| From | To |
| --- | --- |
| `app/gui/recording_factory.py` | `app/recording_factory.py` |
| `app/gui/views/_microphone_check.py` | `app/mic_check.py` |

Qt-free tests that lived in `tests/gui` and cover code that still runs (log filters and rotation, autoload and storage in `bootstrap`, the recording factory, the stuck-recorder exit, the microphone check) move to top-level files in `tests/`.

## Translations

`desktop/renderer/src/i18n/*.json` is the single source of truth for Russian. The `.ts`-derived entries still referenced are merged into those files. `scripts/check_translations.py` lists the Python `mark()` strings and the renderer `$t` strings and fails when one has no Russian entry; `tests/test_translations.py` runs it.

## User-visible consequences

- Users of the classic app get the same application id on Electron. Settings, history and downloaded models are shared and kept: the runtime resolves the same folders.
- There is no CUDA build. Windows inference is CPU (or DirectML where the stock onnxruntime provides it); macOS on Apple silicon uses CoreML.
- The version places are `pyproject.toml`, `app/version.py`, `desktop/package.json` and its lock. `setup.py` is gone.

## Acceptance

- `uv sync --frozen` installs from the regenerated lock; PySide6 is not installed and not importable by the runtime.
- `pytest tests/ -n auto -m "not timing"` is green apart from the files owned by the parallel 010 work, which are listed in the hand-over note.
- `python -c "import app.server.runtime"` works with a meta-path blocker raising on `import PySide6`.
- `scripts/build_server.py` still passes its smoke run.
- `grep` for `PySide6`, `QtWidgets`, `app.gui` finds only historical mentions (specs, changelog).

## Out of scope

Features still missing in Electron (the parity audit in spec 010), the lock rename `LazyToTextQt`, removal of the `system_tray` collaborator in `state_manager`.
