# Changelog

All notable changes to Lazy to Text. Versions are ordered newest first.

Entries describe what changed and why something was worth changing — the
traps that cost a rebuild are recorded in [AGENTS.md](AGENTS.md), not here.
Release assets and their exact sizes are on the
[release page](https://github.com/aa-blinov/lazy-to-text/releases).

## 0.1.5 — 2026-10-11

The version is now readable at the bottom of Settings, where a bug report
asks for it, instead of three interactions away in the About dialog.

### Added

- **Version footer on the Settings view**, pinned to the bottom of the
  window. It sits beside the scroll area rather than at the end of the
  scrolling column, so it stays in view at every scroll position — the
  settings list is taller than any window, so a footer inside it would
  have been below every card.
- **`app/version.py`**, one place that answers "which version is this?".
  The About dialog and the footer read the same string by construction.
- **`test_the_runtime_reports_the_version_the_tree_declares`**, which
  compares what the app *would print* against `pyproject.toml`. The
  existing version tests all compare strings inside the repository, so
  they stayed green while the UI displayed the previous version.

### Fixed

- **Stale installed metadata no longer misreports the version.** After a
  version bump the venv keeps serving the previous `dist-info`, and the
  footer showed `0.1.3` on a tree declaring `0.1.4`. A version that lies
  is worse than no version: the user quotes it in a bug report and
  believes it.

### Changed

- `tests/test_version.py` now requires **exactly one** hardcoded version
  fallback, in one module. It previously accepted two in the About dialog
  and read only the first, which is how the second was free to drift.

## 0.1.4 — 2026-10-11

The macOS bundle now carries the hardened runtime and is signed in a way
that keeps the inference worker alive under it.

### Added

- **Hardened runtime on the release bundle.** Measured before:
  `flags=0x0(none)`; after: `flags=0x10000(runtime)`, `CodeDirectory`
  `v=20400` → `v=20500`. Apple requires this before it will notarize
  anything.
- **`scripts/entitlements.plist`**, declaring `com.apple.security.device.audio-input`.
  The runtime denies what it does not permit, so a hardened dictation app
  records nothing without it.
- **`codesign --verify --deep --strict` as a build gate.** A signature
  that does not verify is worse than no signature, and verifying is a
  separate question from `codesign` exiting 0. A build here once passed
  both the exit-status check and a certificate-anchored requirement check
  while failing `--verify` with *"a sealed resource is missing or
  invalid"* — a gap only Apple's notary service would have surfaced.

### Changed

- **Signing moved from `--deep` to inside-out**: leaves first, bundle last.
  `--deep` signs nested code as a side effect of signing the container,
  which leaves the order to codesign rather than to the build script.
- **Nested code is selected by what it is, not by whether it is
  executable.** 27 Mach-O files under `Contents` carry no execute bit and
  are the load-bearing ones: `libpython3.12.dylib`, which the inference
  worker links against, 22 pyobjc modules behind the autopaste and the
  permission probes, and scipy's gfortran dylibs plus portaudio.
- **The recording overlay follows the cursor.** It anchors to the screen
  under the pointer rather than the primary display — dictation is a
  global hotkey, and a confirmation delivered to the wrong screen is
  worse than none.
- **`setuptools` and `pygments` are out of the bundle**, 7.63 MB of
  build-time cruft that reached the artifact as dependencies of a
  dependency.
- **The file-path resampler is now asserted to be the microphone's
  resampler.** The numpy fallback is not equivalent: on real Russian
  speech it changes 2.13% of words, and it carries roughly twice the
  energy in the 7–8 kHz band because linear interpolation has no
  anti-alias filter.

### Fixed

- **The inference worker no longer dies under the hardened runtime on a
  self-signed build.** The runtime matches loaded libraries against the
  loading process's Team ID, and a certificate you generate yourself never
  has one — so `libpython3.12.dylib` was refused and the worker died on
  its first instruction. The window still opened, because the app falls
  back to the in-process backend; nothing reported an error.
- **Entitlements reach the worker.** `Contents/MacOS/python` is `exec`'d
  in its own right, so the runtime is enforced against its own signature
  and it needed its own entitlements rather than the bundle's.

### Known limitations

- Signed with a self-signed certificate, so **another Mac still requires
  right-click → Open**. TCC grants survive rebuilds on your own machine,
  which ad-hoc signing did not give. Clearing this needs an Apple Developer
  ID ($99/year, waivable for nonprofits, education and government); the
  command sequence is in README under *Notarizing the Mac build*.
- Inference runs on CPU for the default Russian model. Measured choice,
  not a fallback: CoreML takes 81% of the nodes and is still slower.

## 0.1.3 and earlier

- **0.1.3** (2026-10-08) — the About dialog's version fallbacks and the
  version-consistency test.
- **0.1.2** (2026-10-07) — packaging and CI corrections.
- **0.1.1** (2026-10-06) — history and configuration work.
- **0.1.0** (2026-10-05) — first release.