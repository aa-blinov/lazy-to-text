"""Headless runtime for the Electron interface.

The server owns the domain stack: ``ConfigManager``, ``StateManager``, the
inference backend, the hotkey listener, the clipboard manager. The window is
only a view over it.

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
