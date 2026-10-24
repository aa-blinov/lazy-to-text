# Feature Specification: Packaging and Release

> **Note (spec 011):** this spec was written against the former Qt interface. The Electron interface (spec 010) replaced it and the Qt code was removed (spec 011). The behaviour described here is still the behaviour spec of the engine; mentions of `app/gui` below name files that no longer exist, and the equivalent lives in the Electron renderer (`desktop/renderer`) and the runtime (`app/server`).

**Feature Branch**: `[none - baseline]`

**Created**: 2026-10-24

**Status**: Implemented (baseline)

**Input**: User description: "Describe the existing way Lazy to Text is turned from a source tree into artifacts a person can install and run on macOS and Windows: the macOS app bundle, its signing and hardened runtime, the Windows portable bundle and installer (CPU and CUDA variants), the CI workflows, where the version comes from, and how a release is cut."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A Mac user runs a signed, self-contained app (Priority: P1)

A person downloads the macOS archive, drags `Lazy to Text.app` into Applications and opens it. The app has its own name and icon in the Dock, in Cmd-Tab and in System Settings, asks for Microphone and Accessibility access under that name, and keeps the grants across later versions. Dictation works, including pasting, because the bundle carries everything it needs and every piece of code in it is signed.

**Why this priority**: Without a bundle that launches, signs and keeps its permission grants, nothing else in the product reaches the user.

**Independent Test**: Build the release bundle, read back its designated requirement and run the bundled inference worker interpreter; the requirement must anchor on a certificate (not a cdhash) when an identity exists, and the worker must start.

**Acceptance Scenarios**:

1. **Given** a machine with a code-signing identity in the keychain, **When** the release bundle is built, **Then** every Mach-O file, framework and bundle inside it is signed leaf-first with the hardened runtime, the bundle is signed last with the entitlements, the seal verifies, and the designated requirement anchors on the certificate.
2. **Given** a machine with no signing identity, **When** the release bundle is built, **Then** the build signs ad-hoc, says in plain words that Accessibility and Microphone grants will not survive a rebuild, and points at the one-time identity setup script.
3. **Given** a signing identity was chosen (found or supplied through the environment), **When** the resulting designated requirement is a cdhash, **Then** the build fails instead of reporting success.
4. **Given** a finished release bundle, **When** its worker interpreter (`Contents/MacOS/python`) is executed, **Then** it starts, which proves the dynamic library it links is resolvable and that library validation does not reject it.
5. **Given** the app is launched, **When** the user records, **Then** the microphone prompt shows the usage description declared in the bundle and the bundle identity is `ai.eora.lazytotext` in every build.

---

### User Story 2 - A Windows user installs or unzips and runs (Priority: P1)

A Windows user either runs a per-user Setup program or unzips a portable folder and double-clicks `LazyToText.exe`. No administrator rights, no PATH changes, no system-wide ffmpeg or CUDA toolkit are required. The app is windowed (no console), shows its icon and styling, and keeps its data under the per-user directories rather than in the installation folder.

**Why this priority**: Windows is the other first-class platform; a bundle that starts unstyled or dies on a missing metadata folder is an unusable release.

**Independent Test**: Build the folder bundle and the one-file variant from the one spec and compare what each ships: both must contain the `onnx_asr` metadata, the application assets under the same relative location, and the style and translation files.

**Acceptance Scenarios**:

1. **Given** the portable zip is extracted anywhere, **When** `LazyToText.exe` is launched, **Then** the app starts with its assets, styles and translations and writes user data only to the per-user config, log and cache directories.
2. **Given** the Setup program is run without elevation, **When** it completes, **Then** the app is installed under the user's local programs directory, appears in Add/Remove Programs, has a Start Menu entry, and offers optional Desktop and start-with-Windows shortcuts (both unchecked by default).
3. **Given** the app is running, **When** the installer starts, **Then** it detects the running instance through the app's single-instance mutex and asks to close it rather than overwriting live files.
4. **Given** a windowed build where the standard streams are null, **When** a library prints progress (download bars), **Then** the app does not crash, and helper processes spawned for the clipboard or paste do not flash a console window.
5. **Given** the one-file variant is built, **When** it starts, **Then** it behaves like the folder variant, because both come from the same build description rather than two parallel ones.

---

### User Story 3 - A maintainer cuts a release from a tag (Priority: P1)

A maintainer bumps the version in every place that names it, commits, tags `v<version>`, syncs the environment from the lockfile, builds, verifies and pushes the tag. Pushing the tag builds the Windows artifacts and publishes a GitHub Release; the macOS archive is built locally and attached by hand.

**Why this priority**: A release that disagrees with itself about its version, or that is built from a fresh dependency resolution, ships something nobody tested.

**Independent Test**: Run the version tests: all declared versions agree, and the newest `v*` tag equals the version in the tree.

**Acceptance Scenarios**:

1. **Given** a version bump, **When** the version tests run, **Then** `pyproject.toml`, the py2app version, both `Info.plist` version keys and the fallback in `app/version.py` are the same string, and the newest `v*` tag matches it.
2. **Given** a `v*` tag is pushed, **When** the release workflow runs on a Windows runner, **Then** it builds the folder bundle from the locked dependencies, zips it as the portable artifact, compiles the installer, and publishes a GitHub Release with generated notes carrying whichever of the two files exist.
3. **Given** the installer compile fails or Inno Setup is missing, **When** the workflow continues, **Then** the portable zip is still uploaded and released; the installer is optional.
4. **Given** the tag contains a hyphen (for example a pre-release suffix), **When** the release is published, **Then** it is marked as a pre-release.
5. **Given** a manual dispatch, **When** the workflow runs, **Then** artifacts are uploaded to the workflow run only, with a label built from the supplied name (default "manual") and the short commit hash, and no release is published.

---

### User Story 4 - A contributor builds a dev bundle quickly (Priority: P2)

A contributor on a Mac runs the build script with no flags and gets an alias `.app` in seconds: it symlinks back to the source tree and the venv, so edits show up on next launch, while still having the real app identity so permission prompts show the right name.

**Why this priority**: The fast loop is how permission and signing behaviour is tested at all; it is not shipped to users.

**Independent Test**: Run the build script without `--release`; a `Lazy to Text.app` exists under `dist/`, no pruning and no hardened runtime were applied.

**Acceptance Scenarios**:

1. **Given** a synced venv, **When** the script runs in default mode, **Then** it wipes `build/` and `dist/`, refreshes the icon when `iconutil` exists, builds an alias bundle, patches the PortAudio in the venv, and signs with `--deep` without the hardened runtime.
2. **Given** the venv is missing, **When** the script runs, **Then** it stops with a message asking for a prior environment sync.
3. **Given** the script is interrupted or fails, **When** it exits, **Then** `pyproject.toml` is restored to its original content.

---

### User Story 5 - A Windows user with an NVIDIA GPU gets acceleration (Priority: P2)

A user who wants GPU inference either runs a CUDA-named build or launches the CUDA entry point, which installs the GPU runtime if it is missing and falls back to CPU, saying so, when it cannot.

**Why this priority**: It is an optional upgrade over the default CPU build, with the CPU path always remaining.

**Independent Test**: Build with the CUDA wrapper in dry-run mode: it synchronises with the `cuda` extra and stops before bundling; without `--dry-run` it produces a folder named `LazyToText-CUDA`.

**Acceptance Scenarios**:

1. **Given** the CUDA wrapper is run, **When** it completes, **Then** the output is a `LazyToText-CUDA` folder (or `LazyToText-CUDA.exe` for one-file) built from the same spec as the CPU build, with the NVIDIA runtime libraries from the installed packages bundled.
2. **Given** a bundle containing the NVIDIA libraries, **When** the frozen app starts on Windows, **Then** their directories are placed on the library search path before any user code runs.
3. **Given** the CUDA entry point on Windows and no working GPU provider, **When** it starts, **Then** it tries to install the GPU wheel and redistributables, reports success or "falling back to CPU", and then runs the normal launch.

---

### User Story 6 - Every push is tested on all three platforms (Priority: P2)

Every pull request and every push to `prod` or to a `v*` tag runs the full suite on macOS, Windows and Linux, so a platform-specific break is visible before anyone downloads an artifact.

**Why this priority**: The offscreen suite is the only automated protection; it must be honest about which leg failed.

**Independent Test**: Introduce a failing test on one platform; that leg's "Run the suite" step fails and the job is red, independent of the timing pass.

**Acceptance Scenarios**:

1. **Given** a pull request, **When** CI runs, **Then** three legs run with the offscreen Qt platform, dependencies synced with the lockfile frozen, and the main pass and the timing pass are separate steps so a red main pass fails the job.
2. **Given** the Linux leg, **When** it runs, **Then** it has the system libraries Qt, pynput and sounddevice need at import time and runs under a virtual X server.
3. **Given** a `v*` tag push, **When** the tests workflow starts, **Then** the exact tagged commit is tested, although the release workflow does not wait on the result.
4. **Given** one leg fails, **When** the others are healthy, **Then** they still complete (no fail-fast), because the platforms disagreeing is the point of the matrix.

---

### User Story 7 - The project site stays deployed (Priority: P3)

Changes to `docs/` on `prod` publish the project's static site to GitHub Pages, one deployment at a time.

**Why this priority**: Marketing/documentation surface, not the product.

**Independent Test**: Push a change under `docs/` to `prod`; a Pages deployment runs and publishes the folder.

**Acceptance Scenarios**:

1. **Given** a push to `prod` touching `docs/**` or the Pages workflow, **When** the workflow runs, **Then** the `docs` directory is deployed and the URL is reported.
2. **Given** two deployments queue, **When** the second arrives, **Then** it waits instead of cancelling the first.

---

### Edge Cases

- Naming PySide6 submodules instead of the bare package builds cleanly but the bundle dies at launch on a missing module directory; the bare package name is required.
- A Mach-O file without the execute bit (the Python interpreter library, extension modules for the Quartz/AppKit bindings, scipy's runtime libraries, the PortAudio library) must still be signed; selecting code by execute bit ships an app that cannot paste or cannot start its worker.
- A file without a recognisable extension (the bundled ffmpeg binary) and Qt framework binaries inside wrappers must be handled; the selection is by the Mach-O magic within the places code lives.
- A `.pyc` removed from under an existing signature makes the seal invalid with no other symptom; the release build verifies the seal and fails.
- A self-signed identity cannot be given a secure timestamp and cannot carry a Team ID; a timestamp is requested only for an identity named "Developer ID ...", and the local entitlements add one extra key (library validation off) that the Developer ID entitlements must never contain.
- Entitlements on the bundle do not reach the separately executed inference worker; the worker entry point is signed with its own entitlements.
- The worker's interpreter links a library at a path the bundler never creates; the build stages it (symlink, copy as fallback) before signing, and if the source library is absent it warns that the app will fall back to the in-process backend.
- Editing the build script while it runs corrupts the build silently; this is a maintainer rule, not enforced.
- Two certificates with the same signing name make the signing call ambiguous and the build stops at the first nested binary.
- Switching from ad-hoc to a certificate signature once orphans existing permission grants; they must be reset once by hand (the commands are documented).
- Re-resolving dependencies during a release changes what ships; bare resolution that rewrites the lockfile is not allowed in any workflow.
- After a version bump the venv's installed metadata still reports the old version until re-synced; the runtime version test fails until then.
- The download sizes quoted in README and the landing page go stale each release and are only checked against each other, not against the release asset.
- If the Inno Setup compile step fails, its derived output name must still be well-formed so the publish step does not match the whole build directory.
- A bundle built on a machine whose uv-managed Python exposes `zlib` as built-in or whose Tcl/Tk runtime is not discoverable would abort py2app; the build script compensates for both.

## Requirements *(mandatory)*

### Functional Requirements

**macOS bundle**

- **FR-001**: The system MUST produce `Lazy to Text.app` through a single wrapper script with two modes: alias (default, fast, dev only) and `--release` (self-contained, distributable).
- **FR-002**: The bundle MUST use the identifier `ai.eora.lazytotext`, the name and display name "Lazy to Text", a minimum macOS version of 12.0, high-resolution support, and the productivity category.
- **FR-003**: The bundle MUST declare a microphone usage description and an Apple Events usage description, stating that audio never leaves the device and that System Settings is opened only to help grant Accessibility.
- **FR-004**: The bundle MUST NOT be a menu-bar-only agent: it has a Dock icon and Cmd-Tab entry, with the activation policy switched at runtime by the app.
- **FR-005**: The bundle MUST register as an alternate handler for audio and video documents (role Editor) and export its own audio and video type identifiers with the supported file extensions, so Finder "Open With" and double-click can hand a file to the app.
- **FR-006**: The bundle MUST include the first-party `app` package and the named native or lazily imported dependencies in full, MUST name PySide6 as the bare package, and MUST exclude the test tooling, the Tk toolkit, the bundler itself, and the `rubicon` namespace package.
- **FR-007**: The build MUST regenerate the application icon from the same painter the running app uses when `iconutil` is available, and continue with a default icon when it is not.
- **FR-008**: The build MUST temporarily remove the dependency block from `pyproject.toml` so py2app accepts the project, and MUST restore the file on every exit path.
- **FR-009**: The build MUST replace the wheel's PortAudio library with the patched one (built from a pinned source commit with the vendored patch, leaving a marker file naming version, commit and patch) before signing; in alias mode it patches the venv copy instead.
- **FR-010**: In release mode the build MUST prune, before signing, the Qt frameworks, plugins, QML trees, developer tools and codec libraries the app never loads, plus the named pure-Python packages that nothing the app runs imports; in alias mode it MUST NOT prune.
- **FR-011**: The set of Qt modules kept by the prune MUST be a superset of what the app's sources import, and the set of Python packages removed MUST contain nothing the app imports; both are held against the real import graph by tests.
- **FR-012**: The build MUST stage the Python dynamic library at the path the worker interpreter links, before signing.

**Signing and hardened runtime**

- **FR-020**: The signing identity MUST be taken from the environment override when set, otherwise the first usable code-signing identity in the keychain, otherwise ad-hoc.
- **FR-021**: A release bundle MUST be signed with the hardened runtime: nested code first (longest path first so a wrapper is sealed after its contents), the worker entry points with the entitlements file, the bundle last with the entitlements.
- **FR-022**: Code to sign MUST be selected by Mach-O magic within frameworks, bundles, shared objects, dynamic libraries, the `Contents/MacOS` entry points and the bundled ffmpeg, not by execute bit.
- **FR-023**: A Developer ID identity MUST use the entitlements file declaring only audio input and request a secure timestamp; any other identity MUST use the local entitlements file, which adds only the disable-library-validation key, and MUST NOT request a timestamp.
- **FR-024**: Neither entitlements file MAY grant Apple Events automation; Accessibility and Microphone are user grants, not entitlements.
- **FR-025**: A release build MUST verify the bundle with a deep strict verification and fail with a message not to ship the bundle if it does not verify.
- **FR-026**: After signing, the build MUST read the designated requirement; when an identity was chosen and the requirement is a cdhash, it MUST fail; when it anchors on a certificate, it MUST say that grants will survive rebuilds.
- **FR-027**: A signing failure with an identity chosen MUST fail the build and state the bundle is not safe to ship; an ad-hoc failure MUST warn and suggest removing quarantine.
- **FR-028**: The one-time identity setup script MUST create a self-signed code-signing identity, make it usable by `codesign` without a blocking prompt (probing rather than assuming), MUST NOT derive the keychain password, and MUST be run from an interactive desktop session.
- **FR-029**: Alias builds MUST NOT enable the hardened runtime.

**Windows bundle and installer**

- **FR-040**: The Windows artifact MUST be built from one PyInstaller description; the folder bundle is the default and a one-file variant is selected by an environment switch, never by a second hand-written command line.
- **FR-041**: The build description MUST ship assets, style sheets and translations under their `app/...` relative paths, the `onnx_asr` metadata folder and data files, all submodules of `onnx_asr` and `onnxruntime`, and the NVIDIA runtime DLLs of any installed `nvidia-*` packages; hidden imports that are not installed MUST be skipped with a note, not fail the build.
- **FR-042**: The bundle MUST be windowed by default, with a debug-console switch available through an environment variable, use the idle tray icon as its executable icon, and take its folder/exe name from an environment variable defaulting to `LazyToText`.
- **FR-043**: A runtime hook MUST give null standard streams a discarding writer, suppress console windows for spawned helper processes unless a caller sets its own flags, and put bundled NVIDIA library directories on the search path, before application code runs.
- **FR-044**: The CPU wrapper MUST sync from the frozen lockfile and force a clean CPU runtime wheel before building; the CUDA wrapper MUST sync with the `cuda` extra, install the GPU runtime wheel and build with the name `LazyToText-CUDA`; both MUST support clean, one-file, skip-sync and dry-run switches and exit non-zero on any failing step.
- **FR-045**: The installer MUST be per-user by default (no elevation, install under the user's local programs folder, directory page always shown), have a stable application identity so upgrades replace rather than duplicate, register an uninstaller, offer English and Russian, create a Start Menu entry, offer optional Desktop and run-at-login shortcuts (off by default), offer to launch the app at the end, close running instances, and use the same mutex name as the app's single-instance lock.
- **FR-046**: The installer file name MUST be `LazyToText-<version>-setup.exe` and the portable archive `LazyToText-<version>-windows-x64.zip`, where `<version>` carries the short commit hash suffix produced by the workflow.

**Continuous integration and release**

- **FR-060**: Tests MUST run on macOS, Windows and Linux for every pull request, every push to `prod`, every push of a `v*` tag, and on manual dispatch; older runs on the same ref MUST be cancelled.
- **FR-061**: Every workflow that installs dependencies MUST do so from the frozen lockfile so a stale lock fails the run; the release build MUST exclude the development group and install the bundler explicitly.
- **FR-062**: The suite MUST run with the offscreen Qt platform, the full history MUST be fetched so the tag comparison test can run, and on Linux a virtual X server and the Qt, X and audio runtime libraries MUST be provided.
- **FR-063**: The main test pass and the timing test pass MUST be separate steps.
- **FR-064**: A `v*` tag push MUST build on a Windows runner, upload the portable zip and (when it compiled) the installer as workflow artifacts, and publish a GitHub Release with generated notes and the files that exist; a manual dispatch MUST only upload workflow artifacts.
- **FR-065**: The release workflow MUST fail with a clear message when the bundle folder is absent after the build.
- **FR-066**: A house-style check MUST run on every push and pull request, using a pinned external action, and upload its report.
- **FR-067**: A Pages workflow MUST deploy `docs/` on changes to it on `prod`, one at a time without cancelling an in-flight deployment.
- **FR-068**: Dependency update automation MUST run weekly with grouped pull requests.
- **FR-069**: The macOS archive MUST be produced outside CI by archiving the verified bundle with a tool that preserves symlinks and execute bits, verified after archiving, and attached to the release by hand.

**Versioning**

- **FR-080**: The version MUST be declared in `pyproject.toml` (canonical), the py2app `setup()` call, both `CFBundleVersion` and `CFBundleShortVersionString`, and the fallback in `app/version.py`; they MUST be identical.
- **FR-081**: The newest `v*` tag, ordered by version, MUST equal the version in the tree when any tag exists.
- **FR-082**: The runtime version shown in About and the Settings footer MUST come from the installed distribution metadata when readable, fall back to the pinned string otherwise, and never raise; the test compares what would be shown against the tree's declared version.
- **FR-083**: The release order is: bump every place, commit, tag, re-sync the environment from the lockfile, build, verify, push the tag.
- **FR-084**: The download sizes published in README and on the landing page MUST be updated together from the actual release assets; code comments MUST point at them and not restate them.
- **FR-085**: A release entry MUST be added to `CHANGELOG.md` (newest first), describing what changed and why; traps are recorded in the agent documentation, not the changelog.

**Entry points**

- **FR-090**: The package MUST expose two console entry points: the normal launcher and a CUDA launcher that, on Windows, installs the GPU runtime if it is missing before delegating to the normal launch, and on other platforms is identical to it.
- **FR-091**: Optional extras MUST be `cuda` (NVIDIA redistributables) and `darwin` (the AVFoundation binding); the bundlers, the cmake wheel used for PortAudio, and the test tools MUST be in the development group only, scoped to the platform that needs them.

### Key Entities

- **Release artifact**: the macOS archive (built by hand), the Windows portable zip and the Windows Setup program (built by CI), each carrying the version label.
- **Version declaration**: the set of places that name the version and the tag that promises it.
- **Signing identity**: Developer ID, self-signed development certificate, or ad-hoc; decides entitlements, timestamping and whether permission grants persist.
- **Entitlements pair**: the distribution file (audio input only) and the local file (adds library-validation off).
- **Prune manifest**: the keep-list of Qt frameworks and plugin directories and the cut-list of Python packages.
- **Patched PortAudio marker**: the file next to the shipped dynamic library recording the version, commit and patch that produced it.
- **Build description (spec)**: the single PyInstaller description that defines what ships on Windows in both shapes and both variants.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A release macOS bundle built with an identity reports a certificate-anchored requirement, passes deep strict verification, carries the hardened-runtime flag and the audio-input entitlement, and its worker interpreter starts; all of these are checked by tests that run wherever a bundle exists.
- **SC-002**: The shipped bundle carries the patched PortAudio marker; a bundle without it fails the suite.
- **SC-003**: Every Mach-O file the app loads from the bundle is signed (zero unsigned candidates).
- **SC-004**: The version tests pass with zero disagreements between the declared places and the newest tag.
- **SC-005**: All three CI legs run the same collected test count, with skips limited to platform conditionals and the bundle tests that need a built bundle; a leg with fewer tests has failed at collection.
- **SC-006**: A tag push yields a GitHub Release with the portable zip attached in every case, and the Setup program attached whenever its compile succeeded.
- **SC-007**: The folder and one-file Windows variants ship the same set of data and metadata files because they share one description.
- **SC-008**: The published sizes in README and the landing page agree with each other and are re-read from the release at every release.
- **SC-009**: Numbers for size and speed are published only in `README.md` and `docs/index.html` (and model figures in `app/model_mapping.py`), not in this spec or in code comments.

## Assumptions

- The macOS bundle is built on an Apple Silicon Mac with Xcode command-line tools, a synced venv, and Python 3.12 from the project's environment manager.
- The macOS bundle is not notarized; notarization needs a paid Developer ID and is described in README as a future procedure. Without it, other machines require the right-click Open exemption.
- Windows artifacts are built only by the release workflow on a hosted Windows runner (or by the wrappers locally); the CUDA variant has a build wrapper but no CI job.
- Linux has no packaged artifact; it is a test platform and a run-from-source platform only.
- The Windows installer wraps the CPU folder bundle only.
- The release workflow does not wait for the tests workflow; it is not a release gate.
- The house-style standard is owned by an external repository and enforced here by a pinned reference.
- Dependency update automation lists several ecosystems; only the ones with manifests in this repository (workflow actions and Python) are expected to produce pull requests.

## Where it lives

Build descriptions and scripts

- `setup.py` - py2app configuration for the macOS bundle: identity, plist keys, document types, exported types, package include/exclude lists, workarounds for py2app and the uv-managed interpreter; also the version in the `setup()` call and plist.
- `scripts/build-macos.sh` - the macOS wrapper: modes, pyproject strip/restore, icon refresh, PortAudio patch, prune, worker library staging, identity choice, inside-out signing, seal verification, requirement check.
- `scripts/setup-signing.sh` - one-time creation and activation of a self-signed identity.
- `scripts/entitlements.plist`, `scripts/entitlements-local.plist` - the distribution and local entitlements.
- `scripts/prune_bundle.py` - the Qt and Python-package prune, with `--dry-run`.
- `scripts/build_patched_portaudio.py`, `vendor/portaudio/` - patched PortAudio build at a pinned commit, patch file and README.
- `scripts/stress_portaudio_stop.py` - canary for the stop deadlock.
- `scripts/generate_icns.py`, `scripts/generate_tray_icons.py`, `scripts/generate_screenshots.py`, `scripts/update_translations.py` - asset generation helpers used by builds or documentation.
- `lazy_to_text.spec` - the single PyInstaller description (folder and one-file, name and console switches, data and metadata collection, NVIDIA DLL sweep, runtime hook).
- `scripts/pyi_runtime_hook.py` - null-stream shim, no-console child processes, CUDA library path.
- `scripts/build-windows.ps1`, `scripts/build-windows-cuda.ps1`, `scripts/setup-cuda-windows.ps1` - Windows wrappers and the CUDA redistributables installer.
- `installer/lazy_to_text.iss` - Inno Setup per-user installer.
- `pyproject.toml` - canonical version, entry points, extras, development group, pytest configuration.
- `app/version.py` - version reader with pinned fallback; `app/cuda_bootstrap.py` and `main_cuda` in `app/gui/app.py` - GPU upgrade path.
- `lazy-to-text-ui.py` - the thin entry shim both bundlers point at.

Workflows (`.github/workflows/`)

- `tests.yml` - three-platform suite, timing pass, Linux system libraries and virtual X server.
- `release.yml` - Windows build on tag or dispatch, zip, optional installer, artifacts, GitHub Release.
- `pages.yml` - deploys `docs/` on `prod`.
- `house-style.yml` - external house-standard check.
- `ci.yml` - generic check/build workflow whose install, test and build steps are placeholders that only echo; it verifies nothing today.
- `.github/dependabot.yml` - weekly grouped updates.

Documentation

- `README.md` ("Building a release", "Notarizing the Mac build", "macOS first-run permissions"), `CHANGELOG.md`, `AGENTS.md` (release order, manual macOS upload, sizes), `CLAUDE.md` (build, signing, hardened runtime, platform-specific CI notes).

Tests

- `tests/test_version.py` - agreement of declared versions, newest-tag match, runtime-reported version.
- `tests/test_bundle_contents.py` - bare PySide6 naming, Qt subset, prune manifest and prune behaviour, shipped bundle contents, patched PortAudio marker, worker dylib resolution, ad-hoc refusal, setup-signing password rule, entitlement file contents, hardened runtime flags, code selection by type, seal verification, built-bundle entitlements, worker runs, worker signed, every Mach-O signed, size agreement across README and the landing page.
- `tests/test_cuda_bootstrap.py` - GPU probe, install fallback and prompts.
- `tests/test_audio_recorder_stuck_stream.py` and `tests/gui/test_app_exit_stuck_recorder.py` - the second line of defence for the PortAudio deadlock (see spec 008).
