"""Main application window — shell with sidebar navigation and stacked views."""

from __future__ import annotations

import functools
import os
from typing import Dict, Optional

from app.gui.window_chrome import apply_dark_title_bar

from PySide6.QtCore import QByteArray, QEvent, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.views.history_view import HistoryView
from app.gui.views.first_run_view import FirstRunView
from app.gui.views.logs_view import LogsView
from app.gui.views.models_view import ModelsView
from app.gui.views.placeholder import PlaceholderView
from app.gui.views.presets_view import PresetsView
from app.gui.views.shortcuts_view import ShortcutsView
from app.gui.views.transcribe_view import TranscribeView
from app.gui.dock_presence import apply_dock_presence
from app.gui.widgets.recording_overlay import RecordingOverlay
from app.gui.widgets.sidebar import Sidebar
from app.gui.widgets.toast import Toast
from app.gui.widgets.topbar import TopBar
from app.language import bind, tr_format, tr_text


class MainWindow(QMainWindow):
    hidden_to_tray = Signal()
    #: ``(base64 geometry, screen name)``, emitted when the window is
    #: hidden or closed.
    #:
    #: Emitted rather than written here because this window is not given
    #: the config — the controller owns persistence, and every other
    #: piece of state on this app travels that way. The screen *name*
    #: rides along because geometry alone is not enough: a window saved
    #: on a second monitor and restored after that monitor is unplugged
    #: lands at coordinates nobody can reach, which is a worse outcome
    #: than forgetting the position.
    window_state_changed = Signal(str, str)
    #: A path the OS asked us to open — Finder double-click, "Open With",
    #: a drag onto the Dock icon, or the first launch's arguments.
    file_open_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lazy to Text")
        # Floor is 900×620 because that is where every view stops
        # overflowing, measured — not because of a screen size.
        #
        # Qt's own ``minimumSizeHint`` for this layout is 650×532,
        # which is simply wrong: it does not see content minimums. What
        # the layout actually does, with the floor dropped and each
        # view measured for horizontal overflow in its scroll area:
        #
        #   text scale 1.0   700×560  clean on all six views
        #                   650×532  clean on four; Settings overflows 42px
        #   text scale 1.75  900×620  clean on all six views
        #                   760×600  Settings overflows 15px
        #
        # So the honest floor is 900×620 for anyone who raises the text
        # scale, which Settings offers up to 1.75 — a 1366×768 laptop at
        # Windows 150% scaling lands right there. Going lower would mean
        # the Settings view gains a horizontal scrollbar for a setting
        # most people never open.
        #
        # Measured with the floor removed at runtime; the overflow is
        # read off the live scroll area, not inferred from sizes.
        self.resize(1100, 780)
        self.setMinimumSize(900, 620)
        self._close_to_tray = False
        self._quitting = False

        central = QWidget(self)
        central.setObjectName("Central")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.topbar = TopBar(parent=central)
        root.addWidget(self.topbar)

        body = QWidget(central)
        body.setObjectName("Body")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = Sidebar(parent=body)
        self.stack = QStackedWidget(body)

        body_layout.addWidget(self.sidebar)
        body_layout.addWidget(self.stack, 1)

        root.addWidget(body, 1)

        self._views: Dict[str, QWidget] = {}
        self.models_view = ModelsView(parent=self.stack)
        self.transcribe_view = TranscribeView(parent=self.stack)
        self.logs_view = LogsView(parent=self.stack)
        self.shortcuts_view = ShortcutsView(parent=self.stack)
        self.history_view = HistoryView(parent=self.stack)
        self.presets_view = PresetsView(parent=self.stack)
        for key in self.sidebar.items():
            if key == "models":
                view: QWidget = self.models_view
            elif key == "transcribe":
                view = self.transcribe_view
            elif key == "logs":
                view = self.logs_view
            elif key == "shortcuts":
                view = self.shortcuts_view
            elif key == "history":
                view = self.history_view
            elif key == "presets":
                view = self.presets_view
            else:
                view = PlaceholderView(key.capitalize(), parent=self.stack)
            self._views[key] = view
            self.stack.addWidget(view)

        default_key = self.sidebar.active_key()
        if default_key in self._views:
            self.stack.setCurrentWidget(self._views[default_key])

        # First run is a page in the same stack rather than a second
        # top-level window: one window is one thing to close, and a
        # modal splash on top of the app the user just installed reads
        # as an installer nag rather than as the product.
        self.first_run_view = FirstRunView(parent=self.stack)
        self.stack.addWidget(self.first_run_view)
        self._first_run_active = False

        self.sidebar.nav_selected.connect(self._on_nav_selected)
        self.sidebar.width_changed.connect(self.topbar.set_gutter_width)
        self.topbar.set_gutter_width(self.sidebar.width())

        # Floating banner that shows after every successful
        # transcription. Parented to the central widget so it sits
        # above the views; positioned in the top-right by ``Toast``
        # itself.
        self.toast = Toast(parent=central)
        # Separate top-level overlay for the active recording state.
        # Unlike ``toast``, this one is intentionally *not* parented
        # to the main window so it can stay visible while the window
        # is hidden or another app has focus.
        self.recording_overlay = RecordingOverlay()
        self.recording_overlay.visibility_changed.connect(
            self._on_overlay_visibility_changed
        )
        # The window may start hidden in the tray; show/hide events only
        # cover the transitions after this.
        self._sync_dock_presence()
        central.installEventFilter(self)

        # Ctrl+1..9 jump straight to the matching screen — same order as
        # the sidebar. The slice is ``[:9]`` because Ctrl+6..9 are digits,
        # and Qt cannot tell "Ctrl+6" from the numeric keypad's Ctrl+6;
        # the cap keeps the digit row unambiguous rather than binding
        # keys that would shadow each other.
        #
        # The menu owns these bindings, not a parallel list of
        # ``QShortcut``. It used to be the other way round and the
        # Window menu had to list the screens too — two ApplicationShortcut
        # bindings on one key, which Qt resolves by firing both or
        # neither. One control for one decision, the same rule the
        # post-processing card stopped breaking when it dropped its
        # second "Off".
        self._nav_actions: list[QAction] = []

        # Find — Cmd+F on macOS, Ctrl+F on Windows, resolved by Qt's
        # portable key sequence layer the same way Cmd+, and Cmd+Q are.
        # Three of the five views have a search field and none of them
        # had any keyboard route to it, which left a text field that
        # could be reached only by tabbing and never re-entered by
        # muscle memory. ``StandardKey`` rather than a literal sequence
        # so the two platforms get their own modifier without a branch.
        self._find_action = QAction(self)
        self._find_action.setShortcut(QKeySequence.StandardKey.Find)
        self._find_action.setShortcutContext(Qt.ApplicationShortcut)
        self._find_action.triggered.connect(self._on_find_triggered)
        self.addAction(self._find_action)
        # The shortcut follows the view. A view with nothing to search
        # has no Find to offer, and leaving the accelerator live there
        # would be a key that silently does nothing.
        self.sidebar.nav_selected.connect(self._sync_find_action)
        self._sync_find_action(self.sidebar.active_key())

        # Standard "App / About / Settings / Quit" menu — visible
        # under the Apple logo on macOS, in a regular top menu bar
        # on Windows / Linux.
        self._install_app_menu()

        # The app is dark-only, so on Windows the DWM title bar has to
        # be told explicitly — otherwise it follows the system theme
        # and a light system puts a pale strip on a dark window. No-op
        # off Windows.
        apply_dark_title_bar(self)

    def get_view(self, key: str) -> QWidget:
        if key not in self._views:
            raise KeyError(key)
        return self._views[key]

    def set_first_run(self, active: bool) -> bool:
        """Put the first-run page in front, or take it away.

        Returns whether the state actually changed, so the controller
        can skip the config write and the ``completed`` hand-off on a
        repeat call — ``set_first_run(False)`` runs whenever a model
        becomes ready, and "ready" happens more than once.

        The sidebar and the topbar go away with it. They are navigation
        into views that need a working model, and offering five of them
        to someone who has not downloaded one is how a first-run screen
        turns back into the catalogue it was meant to replace.
        """
        active = bool(active)
        if active == self._first_run_active:
            return False

        self._first_run_active = active
        self.sidebar.setVisible(not active)
        self.topbar.setVisible(not active)
        self.stack.setCurrentWidget(
            self.first_run_view if active else self._views[self.sidebar.active_key()]
        )
        if not active:
            self.first_run_view.stop_timers()
        return True

    def is_first_run(self) -> bool:
        return self._first_run_active

    def set_close_to_tray(self, enabled: bool) -> None:
        """When True, the window's close button hides to tray instead of
        quitting; the controller is expected to wire a tray icon that can
        bring the window back. Call ``request_quit`` to bypass the override
        for a real exit."""
        self._close_to_tray = bool(enabled)

    def show_window_if_hidden(self) -> None:
        """Bring the window back from the tray.

        Un-minimises rather than just un-hiding: a window hidden behind
        a minimise is technically visible and technically not there, and
        a user who asked for it back should not have to go looking.
        """
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._sync_dock_presence()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().hideEvent(event)
        self._sync_dock_presence()

    def _on_overlay_visibility_changed(self, _visible: bool) -> None:
        self._sync_dock_presence()

    def _sync_dock_presence(self) -> None:
        """Dock icon only while the main window is up and not dictating."""
        apply_dock_presence(
            main_visible=self.isVisible(),
            overlay_visible=self.recording_overlay.isVisible(),
        )

    def request_quit(self) -> None:
        """Mark the next close as a real quit and close the window."""
        self._quitting = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt naming)
        if self._close_to_tray and not self._quitting:
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
            # Emitted on the way to the tray as well as on a real quit:
            # closing to the tray is the last event before the app runs
            # for hours, and the window the user finds later is the one
            # they expect back exactly where they left it.
            self._emit_window_state()
            return
        try:
            self.recording_overlay.hide()
        except Exception:
            pass
        self._emit_window_state()
        super().closeEvent(event)

    def _emit_window_state(self) -> None:
        """Where the window is, for next launch.

        Skipped while hidden: the tray path calls this after ``hide()``,
        and a hidden window reports the last geometry it had, which is
        usually right but is not worth the write. Actually — it is worth
        the write, since that geometry *is* the one to restore. So this
        runs before the hide on that path too; see ``closeEvent``.
        """
        if self.isMinimized():
            # A minimised window's frame is where it will pop up to,
            # which is rarely where the user put it. The normal
            # geometry is the one they mean.
            return
        state = bytes(self.saveGeometry().toBase64()).decode("ascii")
        screen = self.screen()
        self.window_state_changed.emit(
            state, screen.name() if screen is not None else ""
        )

    def restore_window_state(self, geometry_b64: str, screen_name: str = "") -> bool:
        """Put the window back where it was, if that is still possible.

        Returns whether the position was restored. A window whose old
        screen is gone keeps its size and gets centred on the primary
        one — better than being restored onto a display that does not
        exist, and much better than refusing to start.
        """
        payload = (geometry_b64 or "").strip()
        if not payload:
            return False
        try:
            blob = QByteArray.fromBase64(payload.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            return False
        # Qt's own threshold is four bytes, which anything decodes past.
        # A real geometry blob is a version header plus rectangles and
        # carries well over a hundred bytes, so a short one is a
        # hand-edited or corrupted config rather than a saved window —
        # and restoring it would report success while quietly handing
        # back some default Qt picked.
        if len(blob) < 32:
            return False

        if screen_name:
            available = {s.name() for s in QApplication.screens()}
            if screen_name not in available:
                # Keep the size, drop the position. Centring rather than
                # leaving it wherever Qt decides, so it is never off the
                # edge of a screen that is narrower than it.
                size = self.restoreGeometry(blob)
                if size is None:
                    return False
                self._centre_on_primary()
                return False

        return self.restoreGeometry(blob) is not None

    def _centre_on_primary(self) -> None:
        """Keep the size, drop the position, land in the middle.

        The clamp is the point, with a caveat. A window saved on a
        27-inch display and restored onto a laptop screen can be *wider
        than the work area*, and centring an oversized frame still leaves
        it hanging off — the failure this whole path exists to avoid.

        Two things learned by measuring it. First, the clamp has to be
        applied with ``setGeometry``: clamping a local ``QRect`` and then
        moving to its top-left looks like it clamps and is not, because
        ``move`` positions a window and leaves its size alone. Second,
        ``MainWindow.minimumSize`` is 900x620, so on a screen narrower
        than that the window *cannot* be made to fit and Qt silently
        restores its floor. Best effort, then: centre what cannot fit, and
        only clamp-and-slide what can.

        ``setGeometry`` takes a client rectangle while ``frameGeometry``
        includes the title bar, so the final placement is computed on the
        frame and applied with ``move``.
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()

        rect = self.geometry()
        rect.setWidth(min(rect.width(), area.width()))
        rect.setHeight(min(rect.height(), area.height()))
        rect.moveCenter(area.center())
        self.setGeometry(rect)

        frame = self.frameGeometry()
        self.move(
            self._fitted_origin(frame.left(), frame.width(), area.left(), area.width()),
            self._fitted_origin(frame.top(), frame.height(), area.top(), area.height()),
        )

    @staticmethod
    def _fitted_origin(start: int, size: int, low: int, extent: int) -> int:
        """Where to put a window edge so it is on screen if that is possible.

        When the window is larger than the work area it cannot be made to
        fit, and splitting the overflow evenly — centring — beats any
        slide: one edge ends up flush against the work area and only the
        other overflows, which is how a window ends up at ``-102`` on an
        800-wide screen while the centred answer is ``-52``.
        """
        if size >= extent:
            return low + (extent - size) // 2
        return max(start, low)

    def _searchable_view(self, key: str):
        """The view under *key* if it can take a Find, else ``None``.

        Duck-typed on ``focus_search`` rather than a table of view keys
        and attribute names: the three searchable views disagree about
        what their field is called (``_search`` vs ``_search_edit``),
        and that disagreement is a fact about the views, not something
        the window should have to know. A view that can be searched
        grows the method; a view that cannot simply does not have it.
        """
        view = self._views.get(key)
        if view is not None and callable(getattr(view, "focus_search", None)):
            return view
        return None

    def _sync_find_action(self, key: str) -> None:
        """Enable Find only where there is something to find."""
        self._find_action.setEnabled(self._searchable_view(key) is not None)

    def _on_find_triggered(self) -> None:
        view = self._searchable_view(self.sidebar.active_key())
        if view is not None:
            view.focus_search()

    def _on_nav_selected(self, key: str) -> None:
        # The sidebar is hidden during first run, but its signal is not:
        # Ctrl+1..6 are application shortcuts and do not care whether a
        # widget is visible, so a keystroke would otherwise swap the page
        # underneath a screen that is supposed to be one decision.
        if self._first_run_active:
            return
        if key in self._views:
            self.stack.setCurrentWidget(self._views[key])

    def _activate_nav(self, key: str) -> None:
        """Switch to the named tab — used by the Ctrl+N keyboard
        shortcuts."""
        try:
            self.sidebar.set_active(key)
        except ValueError:
            pass

    def eventFilter(self, watched, event):  # noqa: N802 (Qt naming)
        # Re-anchor the toast on resize so it sticks to the top-right
        # corner regardless of window size.
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Resize and watched is self.centralWidget():
            self.toast.parentResized()
        return super().eventFilter(watched, event)

    def _install_app_menu(self) -> None:
        """Wire the standard ``About / Settings / Quit`` menu items.

        On macOS, Qt promotes any QAction whose ``MenuRole`` is set
        to ``AboutRole / PreferencesRole / QuitRole`` into the global
        Application menu (the one under the Apple logo) regardless
        of which submenu we attach them to — so the host menu's
        title is irrelevant on Mac. On Windows / Linux the same
        actions live in a regular ``Lazy to Text`` top-menu.

        ``Ctrl+,`` and ``Ctrl+Q`` are auto-translated to ``Cmd+,``
        and ``Cmd+Q`` on macOS by Qt's portable key sequence layer
        — matching what every other Mac app shows next to those
        menu items.
        """
        menu_bar = self.menuBar()
        app_menu = menu_bar.addMenu("&Lazy to Text")

        about_action = QAction(self)
        bind(about_action, "setText", "MainWindow", "&About Lazy to Text")
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self._show_about_dialog)
        app_menu.addAction(about_action)

        app_menu.addSeparator()

        settings_action = QAction(self)
        bind(settings_action, "setText", "MainWindow", "&Settings…")
        # Ctrl+, → Cmd+, on macOS via Qt's portable key sequence
        # layer.  ``ApplicationShortcut`` so the binding works even
        # when focus is in a child widget (e.g. log search box).
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.setShortcutContext(Qt.ApplicationShortcut)
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.triggered.connect(self._open_settings_view)
        app_menu.addAction(settings_action)

        app_menu.addSeparator()

        quit_action = QAction(self)
        bind(quit_action, "setText", "MainWindow", "&Quit Lazy to Text")
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.setShortcutContext(Qt.ApplicationShortcut)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self._quit_application)
        app_menu.addAction(quit_action)

        self._build_window_menu()

    def _build_window_menu(self) -> None:
        """The Window menu, which a Mac app is expected to have.

        Two things in it, and the second is the one this app was
        missing. Minimize and Zoom are what users reach for when a
        window is in the way, and having them only in the title bar's
        yellow button is the part of macOS that surprises people coming
        from Windows.

        The screens themselves: the sidebar switches them on ``Ctrl+1``..
        ``Ctrl+N`` and the keys work from anywhere, but a shortcut nobody
        can find is the same as one that does not exist. Listing them
        here makes the navigation discoverable without having to know
        the numbers, and keeps the menu in step with the sidebar rather
        than restating it.
        """
        window_menu = self.menuBar().addMenu("&Window")
        bind(window_menu, "setTitle", "MainWindow", "&Window")

        # PySide6 exposes only a subset of ``QAction.MenuRole`` — there is
        # no MinimizeRole or FullScreenRole on it — so these two are wired
        # by hand rather than tagged. Tagging is still used where it *is*
        # available, because a role is what tells macOS where to place the
        # item without the app guessing.
        minimize = QAction(self)
        bind(minimize, "setText", "MainWindow", "&Minimize")
        minimize.triggered.connect(self.showMinimized)
        window_menu.addAction(minimize)

        # A toggle, not a one-way maximise: on macOS Zoom puts the window
        # back the way it was, and a menu item that cannot be undone is
        # not the same button.
        self._zoom_action = QAction(self)
        bind(self._zoom_action, "setText", "MainWindow", "&Zoom")
        self._zoom_action.triggered.connect(self._toggle_zoom)
        window_menu.addAction(self._zoom_action)

        window_menu.addSeparator()

        for index, key in enumerate(list(self.sidebar.items())[:9], start=1):
            label = self.sidebar.label_for(key)
            action = QAction(f"&{index}  {label}", self)
            action.setShortcut(QKeySequence(f"Ctrl+{index}"))
            action.setShortcutContext(Qt.ApplicationShortcut)
            action.triggered.connect(
                lambda _checked=False, nav_key=key: self._activate_nav(nav_key)
            )
            window_menu.addAction(action)
            self._nav_actions.append(action)

    @staticmethod
    def _paths_from_file_open(payload) -> list[str]:
        """Whatever ``QFileOpenEvent.file()`` handed back, as real paths.

        The obvious reading of that method is wrong on this binding, and
        wrong in a way that looks like it works.

        Qt's C++ API returns a ``QStringList``. Measured on PySide6
        6.11.0, across all three constructors — ``str``, ``QUrl`` and a
        ``file://`` string — ``file()`` returns a **plain ``str``**. So
        the idiomatic ``for path in event.file():`` walks the string
        character by character and emits ``"/"``, ``"U"``, ``"s"``…: one
        single-letter "path" per character of the real filename. Nothing
        raises. The app would have answered a double-click with a burst of
        transcribe attempts on paths that do not exist, each reporting
        that the file is missing.

        A second shape needs handling for the same reason: constructed
        from a URL the same method returns ``file:///tmp/a.wav`` — the
        URL, not the path — and that string is not a file anything can
        open. Both forms are accepted and normalised to a list of
        absolute local paths.
        """
        if payload is None:
            return []
        items = [payload] if isinstance(payload, str) else list(payload)

        paths: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            if text.startswith("file:"):
                # ``toLocalFile`` returns an empty string for a URL that
                # is not local, which then drops the entry instead of
                # forwarding something that cannot be opened.
                text = QUrl(text).toLocalFile()
                if not text:
                    continue
            paths.append(os.path.abspath(text))
        return paths

    def event(self, event: QEvent) -> bool:
        """Catch a file opened from Finder.

        macOS delivers this as a ``QFileOpenEvent``, and a post-and-notify
        against a real ``QMainWindow`` measured it arriving here rather
        than at ``QApplication.event`` — so overriding this is the route
        that works, not merely the one that reads well.

        It is the only route a double-click in Finder has, so a window
        that ignores it accepts the file association and then does
        nothing — which is the worst version of the feature: Finder
        shows the file opening, and nothing opens.

        Handed to a signal rather than transcribing here because this
        class has no recording stack and no business growing one. The
        controller already knows how to open a file; it just needed
        something to tell it.
        """
        if event.type() == QEvent.Type.FileOpen:
            paths = self._paths_from_file_open(event.file())
            for path in paths:
                self.file_open_requested.emit(path)
            # Consumed whenever the event named anything at all. Letting
            # it through would have the base handler try to open a
            # nonexistent file and, on some paths, quit.
            if paths:
                return True
        return super().event(event)

    def queue_file_open(self, path: str) -> None:
        """Announce *path* once the event loop next turns.

        Posted rather than emitted inline so a launch that is also a file
        open does not transcribe behind a first-run screen it never
        showed.

        The timer takes a ``partial``, not the signal's ``emit`` plus a
        trailing argument: PySide6 has no ``singleShot(msec, bound,
        arg)`` overload and raises ``TypeError`` at the call. The shipped
        code used that shape, so the path was dropped with no log line
        and no visible symptom — the app started normally and simply
        never saw the file. That is why this is a method rather than
        three lines in ``main``: a binding that only exists in a
        function nobody can call from a test rots silently.
        """
        QTimer.singleShot(
            0, functools.partial(self.file_open_requested.emit, str(path)),
        )

    def open_paths_from_argv(self, argv) -> list[str]:
        """The files a launch was asked to open.

        The first launch with a path arrives this way — macOS has no
        window yet, so there is no ``QFileOpenEvent`` to intercept —
        and Windows arrives this way always, since it has no equivalent
        event at all.
        """
        found = []
        for arg in list(argv or []):
            text = str(arg).strip()
            if not text or text.startswith("-"):
                continue
            if os.path.exists(text) and os.path.isfile(text):
                found.append(os.path.abspath(text))
        return found

    def _toggle_zoom(self) -> None:
        """Maximise, or put the window back the way it was."""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _open_settings_view(self) -> None:
        """Bring the Settings tab to the front.

        Maps to the sidebar's ``shortcuts`` nav key — the historical
        name from when the view only held hotkey bindings; it has
        since grown into the full settings surface (storage, HF
        token, audio feedback, …) but we kept the key stable to
        avoid migrating the persisted ``Sidebar.active_key`` for
        existing users.

        If the window was hidden to tray when ``Cmd+,`` fires, we
        un-hide and raise it so the user actually sees what they
        opened.
        """
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        self._activate_nav("shortcuts")

    def _quit_application(self) -> None:
        """``Cmd+Q`` / menu ``Quit`` — full app exit, bypassing tray.

        Mirrors what the tray's Quit menu does (see
        ``_tray_mixin._on_tray_quit``): mark the next window close
        as a real quit (so ``closeEvent`` doesn't fall back to
        hide-to-tray), then drop out of Qt's event loop. Without
        the explicit ``app.quit()`` we'd just hide the window —
        ``setQuitOnLastWindowClosed(False)`` is set when the tray
        is alive, so closing the last window doesn't end the
        process by itself.
        """
        self.request_quit()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _show_about_dialog(self) -> None:
        """``About Lazy to Text`` info dialog (app icon + version).

        Pulls the version string from the installed package
        metadata when possible — when running from a wheel /
        ``pip install -e .`` install ``importlib.metadata`` knows
        the canonical version.  Falls back to a hardcoded string
        when running from a raw checkout where no distribution
        metadata exists yet.
        """
        from app.gui.widgets.dialogs import notify
        from app.version import current_version

        version = current_version()

        notify(
            self,
            tr_text("MainWindow", "About Lazy to Text"),
            tr_format("MainWindow", "Lazy to Text %1", version),
            informative=(
                "<p>"
                + tr_text(
                    "MainWindow",
                    "Local-first speech-to-text — Whisper / Parakeet "
                    "/ GigaAM via ONNX Runtime. Apple Silicon goes through "
                    "CoreML (Neural Engine + GPU); NVIDIA goes through "
                    "CUDA / TensorRT.",
                )
                + "</p>"
                '<p><a href="https://github.com/aa-blinov/lazy-to-text">'
                "github.com/aa-blinov/lazy-to-text</a></p>"
            ),
            kind="info",
            rich_text=True,
        )
