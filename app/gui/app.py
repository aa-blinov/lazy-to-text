"""Qt application entry point."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, List, Optional, Tuple

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImageReader,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from app.gui.controllers.app_controller import AppController
from app.gui.log_bridge import QtLogBridge
from app.gui.main_window import MainWindow
from app.language import apply_language
from app.gui.theme import (
    TOKENS,
    apply_theme,
    load_bundled_fonts,
    set_text_scale,
)
from app.utils import is_cached_for_info, is_model_cached, resolve_asset_path
from app.bootstrap import (  # noqa: F401 — re-exported: tests and main() read them here
    _NoSensitiveToFile,
    _apply_hf_token,
    _apply_storage_path,
    _autoload_persisted_model,
    _do_onnx_asr_preimport,
    _install_file_logging,
    _preload_onnx_asr_async,
    _should_show_first_run,
)


def _add_ico_frames(icon: QIcon, ico_path: str) -> int:
    """Add every embedded frame of a Windows ICO file to ``icon``.

    Why we can't just ``QIcon.addFile(path.ico)``: Qt's ICO plugin on
    macOS only loads the file's *first* frame.  Our ``tray_idle.ico``
    bundles 7 sizes from 16 × 16 up to 256 × 256, but QIcon ends up
    holding the 16 × 16 entry only — so the macOS Dock (which wants
    128 × 128) up-scales it from 16 px and the user sees a blurry
    blob instead of the real logo.

    Iterating frames via ``QImageReader.jumpToImage`` lets us pull
    every embedded size into the QIcon's pixmap cache, and macOS
    then picks the closest match to the requested rendering size.

    Returns the number of frames successfully added.
    """
    reader = QImageReader(ico_path)
    if not reader.canRead():
        return 0
    frame_count = reader.imageCount() or 1
    added = 0
    for i in range(frame_count):
        if not reader.jumpToImage(i):
            break
        image = reader.read()
        if image.isNull():
            continue
        icon.addPixmap(QPixmap.fromImage(image))
        added += 1
    return added


# Accent gradient for the squircle Dock icon — the ``accent`` /
# ``accent_focus`` pair from ``app.gui.theme``.  Vertical top-to-bottom
# gradient gives a subtle sheen that reads as "modern app" without
# overpromising depth.  ``accent_focus`` rather than ``accent_hover``:
# the icon is a brand mark, not a control, so it wants the palette's lit
# value and not the 3% nudge a pointer hover gets.  Rendered both ways
# at 256 px and the difference is barely there, so this is the weaker of
# the two claims in this file.
#
# Resolved where the gradient is built, not here: the theme swap
# replaces the contents of ``TOKENS.colors`` in place, so these two used
# to freeze whatever palette was live at import and the Dock icon kept
# the old accent after a switch. The icon is rendered once per launch
# and does not repaint on a theme change, which is a separate question —
# it is a brand mark, not a surface.
# The app mark is a fixed brand colour, not a theme token: the tokens swap with
# the light and dark themes, and the icon must not change with them. Values are
# the dark palette in DESIGN.md (accent sage, and the ground used as ink).
_BRAND_FILL = QColor("#83a598")
_BRAND_INK = QColor("#1d2021")
# Apple's iOS / macOS app-icon shape is a *superellipse* (Lamé curve
# ``|x|^n + |y|^n = 1``), not a rounded rectangle: rounded rects
# join straight edges to circular corners with a visible curvature
# discontinuity (G1 only), while a superellipse has a smooth
# curvature derivative all the way around (G2).  ``n ≈ 4`` is the
# closest single-exponent superellipse to Apple's actual app-icon
# silhouette — slightly rounder than ``n = 5``, less square at the
# corners, and visually matches what shows up next to it in the
# Dock (Steam, Music, Calculator, …).
_DOCK_SUPERELLIPSE_N = 4.0
# Apple's app-icon grid: the icon body is 824 px of a 1024 px canvas,
# centred, with the rest left transparent for the Dock shadow.
_DOCK_ICON_OCCUPANCY = 824 / 1024
# Heroicons microphone-solid is rendered at ~50 % of the icon width
# so it sits centred with comfortable padding — the proportion most
# Mac apps with single-glyph logos (Slack mic, Zoom mic, etc.) use.
_DOCK_FOREGROUND_RATIO = 0.50


def _build_superellipse_path(size: float, n: float = _DOCK_SUPERELLIPSE_N) -> QPainterPath:
    """Build a superellipse (Lamé curve) path inscribed in a
    ``size × size`` square — the actual macOS / iOS app-icon shape.

    Parametric form (centred on origin, half-width = a):
        x(t) = sgn(cos t) · a · |cos t|^(2/n)
        y(t) = sgn(sin t) · a · |sin t|^(2/n)

    n = 2  → a regular ellipse (circle when a = b)
    n = 4  → classic squircle, a touch boxier
    n = 5  → close to Apple's actual app-icon shape
    n = 6+ → approaches a square

    A 240-segment polyline is more than enough for the antialiased
    Dock thumbnail; the eye can't tell apart from a true G2 curve
    at any Dock size.
    """
    cx = size / 2.0
    cy = size / 2.0
    a = size / 2.0

    path = QPainterPath()
    steps = 240
    exp = 2.0 / n
    for i in range(steps + 1):
        t = 2.0 * math.pi * i / steps
        ct = math.cos(t)
        st = math.sin(t)
        x = cx + a * math.copysign(abs(ct) ** exp, ct)
        y = cy + a * math.copysign(abs(st) ** exp, st)
        if i == 0:
            path.moveTo(QPointF(x, y))
        else:
            path.lineTo(QPointF(x, y))
    path.closeSubpath()
    return path


def _render_glyph(svg_path: str, size: int, color: QColor) -> Optional[QPixmap]:
    """Rasterise a monochromatic SVG into a solid-colour, transparent pixmap
    suitable for compositing onto the Dock squircle.

    The SVGs we ship (Heroicons) declare ``fill="currentColor"`` /
    ``stroke="currentColor"``, so ``QSvgRenderer`` paints them in
    whatever pen colour is active — black by default. We render
    once, then replace the result's black pixels with white via the
    ``CompositionMode_SourceIn`` trick: filling a rect over the
    rasterised glyph keeps only pixels where the original alpha
    channel was non-zero, so the glyph silhouette becomes a solid
    white shape.
    """
    if not svg_path or not os.path.isfile(svg_path):
        return None
    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        return None
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), color)
    finally:
        painter.end()
    return pixmap


def _render_dock_icon_at(size: int) -> QPixmap:
    """Render the Dock-style squircle app icon at ``size × size`` px.

    Layers (bottom-up):
      1. Transparent margin matching Apple's 824/1024 design grid
         so the visible squircle sits at ~80 % of the canvas — same
         occupancy as system apps (Music, Calculator, Photo Booth).
      2. Superellipse (G2 squircle) filled with the accent gradient.
      3. Heroicons ``microphone-solid`` glyph in white, centred at
         ~50 % of the squircle width.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)

        inner_size = size * _DOCK_ICON_OCCUPANCY
        offset = (size - inner_size) / 2.0

        # Background squircle (true superellipse, not a rounded rect),
        # translated by ``offset`` so it sits centred inside the
        # design-grid margin.
        path = _build_superellipse_path(inner_size)
        path.translate(offset, offset)
        # Flat fill: DESIGN.md allows no gradients in the system.
        painter.fillPath(path, _BRAND_FILL)

        # Foreground microphone glyph, sized relative to the inner
        # squircle (not the full canvas) so it stays at the visual
        # 50 % proportion users see in other Dock icons.
        glyph_size = int(inner_size * _DOCK_FOREGROUND_RATIO)
        glyph = _render_glyph(
            resolve_asset_path("gui/styles/icons/microphone-solid.svg"),
            glyph_size,
            _BRAND_INK,
        )
        if glyph is not None:
            glyph_offset = (size - glyph_size) // 2
            painter.setClipPath(path)
            painter.drawPixmap(glyph_offset, glyph_offset, glyph)
    finally:
        painter.end()
    return pixmap


def _build_macos_dock_icon() -> QIcon:
    """Programmatically assemble a Mac-native Dock app icon.

    Renders the squircle + microphone composite at every Dock size
    macOS asks for (16 / 32 / 64 / 128 / 256 / 512 / 1024) so the
    same QIcon answers crisply on @1x and @2x density displays
    without re-rasterising on demand.
    """
    icon = QIcon()
    for size in (16, 32, 64, 128, 256, 512, 1024):
        icon.addPixmap(_render_dock_icon_at(size))
    return icon


def _load_app_icon() -> QIcon:
    """Build the QIcon used for the app's window / taskbar / Dock.

    macOS gets a procedurally-rendered squircle (gradient + Heroicons
    microphone) so the Dock and Cmd-Tab show a sharp, on-brand icon
    at every size the system asks for. Other platforms fall back to
    the bundled multi-resolution ICO + PNG so taskbar / Alt-Tab pick
    the right embedded size.
    """
    if sys.platform == "darwin":
        return _build_macos_dock_icon()

    icon = QIcon()
    ico_path = resolve_asset_path("assets/tray_idle.ico")
    if ico_path and os.path.isfile(ico_path):
        _add_ico_frames(icon, ico_path)
    png_path = resolve_asset_path("assets/tray_idle.png")
    if png_path and os.path.isfile(png_path):
        icon.addFile(png_path)
    return icon


def build_application(
    argv: Optional[List[str]] = None,
    theme: str = "dark",
    config: Optional[Any] = None,
    history: Optional[Any] = None,
    recording: Optional[Any] = None,
    tray: Optional[Any] = None,
    install_logs: bool = False,
) -> Tuple[QApplication, MainWindow]:
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    # When a tray icon is present, the window can be hidden indefinitely; we
    # need to keep the app alive even when no top-level window is visible.
    # Without a tray the default behaviour (quit on last closed) is correct.
    if tray is not None:
        app.setQuitOnLastWindowClosed(False)
    icon = _load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    # Text scale has to be in effect *before* the first stylesheet is
    # built, otherwise the window paints once at 100% and then resizes
    # itself in front of the user on startup.
    if config is not None:
        try:
            set_text_scale(config.get_setting("ui", "text_scale"))
        except Exception:  # pragma: no cover — never block startup
            pass
    # Read from the same config the rest of startup uses, so the window
    # is painted once in the theme it will stay in. Resolving "system"
    # here rather than in ``main()`` keeps the default in one place: a
    # caller passing ``theme="system"`` and a stored ``system`` cannot
    # disagree about what that means.
    theme = "system"
    if config is not None:
        stored = config.get_setting("ui", "theme")
        if stored:
            theme = str(stored)
    apply_theme(app, theme)

    # Before the window is built, so its text is born in the right language.
    apply_language(app, config.get_setting("ui", "language") if config is not None else None)

    window = MainWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)
    if install_logs:
        # NB: ``main()`` is responsible for setting the root level + file
        # handler before this function runs so the recording stack's INFO
        # messages aren't lost. Here we just attach the UI bridge.
        bridge = QtLogBridge(parent=window)
        bridge.record_received.connect(window.logs_view.append_record)
        bridge.install()
    if config is not None:
        AppController(
            config=config,
            window=window,
            history=history,
            recording=recording,
            tray=tray,
        )
        if recording is not None:
            recording.setParent(window)
            recording.start()
    if tray is not None:
        tray.setVisible(True)
    return app, window


def _recording_thread_stuck(recording_controller) -> bool:
    """True when a recording thread is still alive after the shutdown.

    A recording thread that cannot be stopped is parked inside
    PortAudio's stop path. It holds the GIL and the microphone, and
    ``Pa_Terminate`` deadlocks on the way out — so the process would
    linger with no window while still owning the single-instance lock,
    and every later launch would be refused. The patched PortAudio in
    the bundle makes the stop path safe, but the app must not depend on
    that to be able to quit.

    Split out of ``main`` so the branch can be asserted directly instead
    of matched as source text.
    """
    if recording_controller is None:
        return False
    probe = getattr(recording_controller, "recording_thread_stuck", None)
    if not callable(probe):
        return False
    try:
        return bool(probe())
    except Exception:  # pragma: no cover — defensive
        return False


def _warn_duplicate_instance() -> None:
    """Say, in ``app.log``, that this process refused to start.

    The single-instance gate is the earliest point at which the app can
    decline to run, and a refusal nobody can find afterwards is the same
    as an app that will not launch: the second process has no window,
    ``LSUIElement`` means no Dock icon to click again, and a Finder
    double-click hands the process no tty, so the ``stderr`` fallback
    disappears with it. Measured before this existed — a second instance
    launched while the first held the lock exited 0 and left zero lines
    in the log.

    Split out of ``main`` so the branch can be asserted directly instead
    of matched as source text.
    """
    import logging as _l

    _l.getLogger(__name__).warning(
        "Another instance holds the single-instance lock — this process "
        "is a second copy and will exit without opening a window. If no "
        "window appears, use the menu-bar icon, or Force Quit the other "
        "copy.",
    )


# How long ``main()`` waits for a freshly spawned inference worker before
# giving up and using the in-process backend. Only ever paid on a broken
# bundle: a healthy worker acks in well under a second, because the ack
# is sent before any model is loaded.
_WORKER_START_TIMEOUT = 10.0


def main() -> int:
    import logging
    import multiprocessing

    # Frozen / py2app builds re-exec the bundle's launcher when
    # ``multiprocessing.spawn`` starts a worker.  Without
    # ``freeze_support`` that re-exec re-enters ``main()`` instead
    # of the worker's target, leaks dozens of half-started Qt
    # windows, and our ``Subprocess init failed: Worker pipe
    # closed before init`` warning fires because the worker
    # never made it to the ``init`` ack.  Calling here is a no-op
    # in dev (``uv run``) — it only takes effect when ``sys.frozen``
    # is set, which py2app does inside the bundle.
    multiprocessing.freeze_support()

    # Auto-install CUDA redistributables on Windows when an NVIDIA
    # GPU is present but the runtime DLLs are missing.  This keeps
    # ``uv run lazy-to-text-ui`` as the single entry point — no
    # manual ``pip install [cuda]`` required.  Fast no-op (<10 ms)
    # when CUDA already works or no GPU exists.
    try:
        from app.cuda_bootstrap import ensure_cuda
        ensure_cuda()
    except Exception:
        pass  # never block startup over bootstrap noise

    # Read the configured ``storage.models_dir`` (may be empty for
    # 'use the default') from config.yaml, then plant ``HF_HOME``
    # BEFORE huggingface_hub gets imported.  ConfigManager itself
    # doesn't pull in HF so we can safely import it first.
    from app.config_manager import ConfigManager

    _early_config = ConfigManager()
    storage_root = _apply_storage_path(
        _early_config.get_setting("storage", "models_dir")
    )
    _apply_hf_token(_early_config.get_setting("huggingface", "token"))

    from app.gui.controllers.recording_controller import RecordingController
    from app.gui.recording_factory import build_recording_stack
    from app.gui.widgets.tray_icon import AppTrayIcon
    from app.instance_manager import try_acquire_single_instance
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    # Before the gate, not after: the gate can refuse to start the app,
    # and the refusal is the one event nobody can reproduce on demand
    # afterwards — by the time anyone reads app.log the second process is
    # long gone and left no trace.
    # ``_early_config`` is built above, before the gate, so the handler
    # is driven by the same config.yaml everything else reads. Calling
    # this without it would fall back to the hardcoded defaults and
    # leave the ``logging`` section decorative again — which is exactly
    # what it was.
    _install_file_logging(_early_config)

    instance_handle = try_acquire_single_instance("LazyToTextQt")

    # Bring up QApplication regardless of branch — both the primary path
    # and the duplicate-warning dialog need our app icon to show in
    # taskbar / Alt-Tab instead of the Python interpreter's icon.
    from PySide6.QtWidgets import QMessageBox

    qt_app = QApplication.instance() or QApplication(sys.argv)
    # Register the bundled Inter font as early as possible so any QFont
    # resolution further down in the stack (icons, message boxes,
    # tooltips spun up before ``apply_theme`` runs) doesn't trigger the
    # ``qt.qpa.fonts: Replace uses of missing font family "Inter"``
    # warning. Idempotent if called again from ``apply_theme``.
    load_bundled_fonts()
    _early_icon = _load_app_icon()
    if not _early_icon.isNull():
        qt_app.setWindowIcon(_early_icon)

    if instance_handle is None:
        _warn_duplicate_instance()
        # Use an explicit QMessageBox instance + exec() rather than the the
        # static QMessageBox.warning(None, ...) — the latter crashed with
        # an access violation when invoked early in the process lifetime.
        try:
            msg = QMessageBox()
            if not _early_icon.isNull():
                msg.setWindowIcon(_early_icon)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Lazy to Text")
            msg.setText(
                "Another copy of Lazy to Text is already running.\n\n"
                "Use its system tray icon to bring it back, or quit it first."
            )
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
        except Exception:
            print(
                "Lazy to Text: another instance is already running.",
                file=sys.stderr,
            )
        return 0

    # We are the primary instance — bind the lock handle so it survives.
    qt_app._instance_mutex = instance_handle  # type: ignore[attr-defined]

    # Spawn the inference worker as the very first thing after the
    # single-instance gate.  Windows ``multiprocessing.spawn`` re-execs
    # Python and re-imports onnx_asr (~3-7 s on a cold start); doing it
    # now lets that work overlap with logging + recording-stack +
    # MainWindow construction below, so by the time we hit
    # ``window.show()`` the worker has usually finished init and the
    # first ``backend.load()`` (autoload) ack-roundtrips in <50 ms
    # instead of stalling the UI.
    #
    # ``SubprocessBackend.__init__`` is async — it returns once the
    # child process is started + the init command has been written to
    # the pipe; the worker's ack is consumed by the reader thread and
    # any later ``_send_cmd`` blocks on the init event until ready.
    #
    # Inside a py2app .app on macOS the worker runs too, but the child
    # needs two things the plain spawn path did not have: the bundle's
    # interpreter (redirected by ``SubprocessBackend``) with its stdlib
    # on ``PYTHONPATH``, and ``libpython`` staged where that interpreter's
    # ``@executable_path/../lib/`` lookup finds it (done in
    # ``scripts/build-macos.sh``).  With those in place the worker starts,
    # and the separate process is what keeps the window responsive:
    # ONNX Runtime's pybind11 bindings never release the GIL during
    # session creation, so an in-process load starves every Python slot
    # for ~0.3 s — measured, against ~8 ms for ordinary thread
    # contention.
    #
    # If the worker cannot start we fall back to the in-process backend
    # rather than shipping a dictation app with no engine at all.
    _whisper_cfg = _early_config.get_whisper_config()
    _backend_kwargs = dict(
        model=_whisper_cfg.get("model") or "whisper-large-v3-turbo",
        device=str(_whisper_cfg.get("device", "auto")),
        compute_type=str(_whisper_cfg.get("compute_type", "float16")),
        language=_whisper_cfg.get("language") or None,
        beam_size=int(_whisper_cfg.get("beam_size", 5)),
    )
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        from app.backends.registry_backend import RegistryBackend
        from app.backends.subprocess_backend import SubprocessBackend

        _early_backend = SubprocessBackend(**_backend_kwargs)
        if _early_backend.wait_for_worker(_WORKER_START_TIMEOUT):
            logging.getLogger(__name__).info(
                "macOS bundle: inference worker is up — model loads run in "
                "a separate process, so the window keeps painting while "
                "ONNX Runtime initialises.",
            )
        else:
            # Never ship a half-working backend: if the worker did not
            # come up, an in-process one still transcribes, it just holds
            # the GIL while ORT initialises. A worse UI, but a working
            # dictation app, and an error the user can act on in the log
            # instead of a feature that silently does nothing.
            logging.getLogger(__name__).error(
                "Inference worker did not come up within %.0fs — falling "
                "back to the in-process backend. The window may lag for a "
                "moment on each model load; dictation still works.",
                _WORKER_START_TIMEOUT,
            )
            try:
                _early_backend.shutdown()
            except Exception:  # pragma: no cover — defensive
                pass
            _early_backend = RegistryBackend(**_backend_kwargs)
    else:
        from app.backends.subprocess_backend import SubprocessBackend

        _early_backend = SubprocessBackend(**_backend_kwargs)

    # The logging pipeline is already installed (see the call above the
    # single-instance gate) so that build_recording_stack's HotkeyListener /
    # model-load messages reach both the UI Logs view and logs/app.log.

    # Reuse the early config — re-creating it would re-read the YAML
    # and just produce identical state, but the early one was made
    # before the logging file handler was attached, so log messages
    # from the load path went to stderr only. That's fine; we don't
    # need them in app.log.
    config = _early_config
    logging.getLogger(__name__).info(
        "Models root: %s (configured=%r)",
        storage_root,
        _early_config.get_setting("storage", "models_dir"),
    )

    state_manager = None
    hotkey_listener = None
    backend = None
    recording_controller = None
    try:
        # Pass the pre-spawned backend in so build_recording_stack
        # doesn't create a second one — the early-spawned worker has
        # already started initialising in parallel.
        state_manager, hotkey_listener, backend = build_recording_stack(
            config_manager=config,
            backend=_early_backend,
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Recording stack failed to initialise — UI will run without "
            "hotkeys/transcription: %s", exc,
        )

    if state_manager is not None:
        recording_controller = RecordingController(
            state_manager=state_manager,
            hotkey_listener=hotkey_listener,
        )

    history = state_manager.history_manager if state_manager is not None else None

    # qt_app already exists from the single-instance gate above.
    tray: Optional[AppTrayIcon] = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = AppTrayIcon(parent=qt_app)
    else:
        logging.getLogger(__name__).warning(
            "System tray not available — close button will quit the app."
        )

    app, window = build_application(
        config=config,
        history=history,
        recording=recording_controller,
        tray=tray,
        install_logs=True,
    )

    # Before ``window.show()``: a first run that reveals the sidebar
    # half a second after launch is a flicker, not an introduction.
    # ``has_model_on_disk`` is False only on an install that has never
    # downloaded anything, which is the one case where there is nothing
    # to dictate with and therefore nothing to say on the setup screen.
    _has_model = _autoload_persisted_model(backend, config)
    window.set_first_run(_should_show_first_run(config, _has_model))

    # Live CPU / RAM / GPU stats in the topbar — polls every 2 s and
    # pushes numbers straight to the widget via signal.
    from app.resource_monitor import ResourceMonitor

    resource_monitor = ResourceMonitor(parent=window)
    resource_monitor.metrics_updated.connect(window.topbar.set_resource_metrics)
    resource_monitor.start()

    window.show()

    # A launch that was handed files. On macOS the *first* open arrives
    # here rather than as a ``QFileOpenEvent``: the event is for an app
    # that is already up, and a window that did not exist when Finder
    # sent it has nothing to deliver it to. On Windows it is the only
    # route there is.
    #
    # Posted through the event loop rather than called inline, so it
    # lands after the first-run decision below has been applied — a
    # first launch that is also a file open should not transcribe behind
    # a setup screen it never showed.
    # Posted through the event loop rather than called inline, so it
    # lands after the first-run decision below has been applied — a
    # first launch that is also a file open should not transcribe behind
    # a setup screen it never showed.
    #
    # ``partial`` rather than ``singleShot(0, emit, path)``: PySide6 has
    # no overload that takes a bound method plus an extra argument. The
    # shapes it accepts are ``(msec, context, functor)`` and
    # ``(msec, functor)``, and passing ``emit`` with a trailing argument
    # raises ``TypeError`` at the call — so the launch argument was
    # dropped on the floor with nothing logged and no visible failure.
    for _startup_path in window.open_paths_from_argv(sys.argv[1:]):
        window.queue_file_open(_startup_path)

    # macOS Dock-click handling: when the user clicks the app's Dock
    # icon while the main window is hidden (close button → tray
    # path), Qt fires ``applicationStateChanged(ApplicationActive)``
    # but does NOT restore the window for us.  Listen for the
    # transition and unhide / raise / activate the window so the
    # Dock icon behaves like every other Mac app.  Skip on
    # Windows / Linux — the tray icon is the canonical restore
    # affordance there, not the taskbar / launcher button.
    if sys.platform == "darwin":
        from PySide6.QtCore import Qt as _Qt

        def _on_application_state_changed(state) -> None:
            if state != _Qt.ApplicationState.ApplicationActive:
                return
            if window.isVisible():
                # User just brought the existing window back to
                # focus — macOS handles the layering for us if the
                # window is visible.
                return
            window.showNormal()
            window.raise_()
            window.activateWindow()

        app.applicationStateChanged.connect(_on_application_state_changed)

    # Run the persisted-model autoload on a daemon thread so the Qt
    # main thread isn't blocked if the worker process is still finishing
    # its init when we get here.  ``backend.load()`` calls
    # ``SubprocessBackend._send_cmd`` which waits on the worker's
    # ``_init_event`` — that wait can take a couple of seconds on a
    # cold start (Windows ``spawn`` + onnx_asr re-import).  Doing it
    # off the main thread means the window is fully interactive
    # straight away; the loading pill / topbar progress paint as soon
    # as the worker is ready.
    import threading as _threading

    _threading.Thread(
        target=_autoload_persisted_model,
        args=(backend, config),
        daemon=True,
        name="autoload-model",
    ).start()

    exit_code = 0
    try:
        exit_code = app.exec()
    finally:
        # Every exit path — tray Quit, Cmd+Q, window close — drops out of
        # ``app.exec()`` and lands here, which is what makes this the one
        # place that can flush ``config.yaml``.
        #
        # ``update_user_setting`` writes on a daemon thread precisely so
        # the Qt thread never blocks on a slow disk. A daemon thread is
        # killed at interpreter exit, so without this a setting changed
        # inside the write window is simply lost — the user changes a
        # hotkey and quits, and the hotkey is not there next launch. The
        # lock drain is bounded, and it is first in the chain because
        # everything after it can block.
        try:
            if _early_config is not None and not _early_config.flush_pending_writes():
                logging.getLogger(__name__).warning(
                    "Config writer was still running at exit — the last "
                    "setting change may not have reached disk.",
                )
        except Exception:  # pragma: no cover — defensive
            pass
        try:
            resource_monitor.stop()
        except Exception:  # pragma: no cover — defensive
            pass
        if recording_controller is not None:
            recording_controller.shutdown()
        if backend is not None:
            backend.shutdown()
        if tray is not None:
            tray.setVisible(False)

        # A model load still parked inside ONNX Runtime keeps the GIL,
        # so returning from ``main()`` does not end the process — the
        # interpreter waits for that thread. The UI is already gone at
        # this point, so what the user gets is a process with no window,
        # no Dock icon and no way to relaunch: every launch in that
        # window is refused by the single-instance lock. Leave instead of
        # waiting, and say so in the log first so the exit isn't silent.
        #
        # A recording thread that could not be stopped is the same
        # failure in a different place: it is parked inside PortAudio's
        # stop path, holding the GIL and the microphone, and
        # ``Pa_Terminate`` deadlocks on the way out. The patched
        # PortAudio in the bundle makes that path safe, but the app must
        # not depend on it to be able to quit — an app that cannot quit
        # is the failure that outlives the next launch.
        probe = getattr(backend, "load_in_flight", None)
        stuck = False
        if callable(probe):
            try:
                stuck = bool(probe())
            except Exception:  # pragma: no cover — defensive
                stuck = False
        stuck = stuck or _recording_thread_stuck(recording_controller)
        if stuck:
            import logging as _l

            _l.getLogger(__name__).warning(
                "A model load or a microphone recording was still running "
                "at exit — leaving immediately instead of waiting for the "
                "interpreter to finalize.",
            )
            for _handler in _l.getLogger().handlers:
                try:
                    _handler.flush()
                except Exception:  # pragma: no cover — defensive
                    pass
            os._exit(exit_code)

    return exit_code


def main_cuda() -> int:
    """Entry point for GPU-accelerated launch (``lazy-to-text-ui-cuda``).

    On Windows: unconditionally installs ``onnxruntime-gpu`` + CUDA
    redistributables if they are missing, then delegates to ``main()``.
    On other platforms this is identical to ``main()``.
    """
    if sys.platform == "win32":
        from app.cuda_bootstrap import (
            _cuda_probe,
            _install_cuda_redist,
            _install_onnxruntime_gpu,
        )
        from app.utils import _try_inject_nvidia_pip_dll_paths

        _try_inject_nvidia_pip_dll_paths()
        if not _cuda_probe():
            print("Setting up GPU acceleration for NVIDIA...")
            if not _install_onnxruntime_gpu():
                print("Failed to install onnxruntime-gpu, falling back to CPU.")
            elif not _install_cuda_redist():
                print("Failed to install CUDA libraries, falling back to CPU.")
            else:
                _try_inject_nvidia_pip_dll_paths()
                if _cuda_probe():
                    print("GPU acceleration ready.")
                else:
                    print("GPU setup incomplete, falling back to CPU.")
    return main()


if __name__ == "__main__":
    raise SystemExit(main())
