"""Headless runtime for the Electron interface.

The Qt application and this server are two front ends over the same
domain stack: ``ConfigManager``, ``StateManager``, the inference backend,
the hotkey listener, the clipboard manager. Nothing in here imports
PySide6, so the server can ship without the Qt libraries.

The Electron app starts it as a child process and talks to it over a
loopback HTTP channel protected by a per-launch token:

``POST /rpc``
    ``{"method": "...", "params": {...}}`` -> ``{"result": ...}`` or
    ``{"error": {"code": "...", "message": "..."}}``.
``GET /events``
    Server-sent events. Each event is ``event: <name>`` plus one JSON
    ``data:`` line. Sticky events are replayed to a new subscriber.

The wire contract is written down in ``docs/ELECTRON.md``.
"""
