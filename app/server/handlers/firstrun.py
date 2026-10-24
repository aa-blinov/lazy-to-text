"""First run: whether to show the setup screen, and how it ends.

The decision itself is ``bootstrap._should_show_first_run`` (a model on disk
always wins, otherwise the ``onboarding.complete`` flag). The three ways the
screen ends are separate on purpose:

``firstrun.complete``  the "Start dictating" button on the last step; the only
                        thing that writes the flag.
``firstrun.defer``     "Set up later" and "See all models instead". Qt built the
                        first button with no handler. Here both end first-run
                        mode for this session and nothing else: the flag stays
                        unset, so the screen returns on the next launch while no
                        model is on disk, which is what spec 002 FR-075 says.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.server.rpc import method

log = logging.getLogger(__name__)


def _has_model(rt: Any) -> bool:
    """A live disk check, not the start-up value: a model downloaded in this
    session must count, or a reloaded window would be sent back to step 1."""
    from app.model_mapping import MODELS
    from app.utils import is_cached_for_info

    for info in MODELS:
        try:
            if is_cached_for_info(info):
                rt.has_model_on_disk = True
                return True
        except Exception:  # pragma: no cover - defensive
            continue
    return bool(getattr(rt, "has_model_on_disk", False))


def _status(rt: Any) -> Dict[str, Any]:
    from app import bootstrap
    from app.model_mapping import display_order

    deferred = bool(getattr(rt, "first_run_deferred", False))
    wanted = bootstrap._should_show_first_run(rt.config, _has_model(rt))
    cfg = rt.config
    return {
        "show": bool(wanted and not deferred),
        "deferred": deferred,
        "complete": bool(cfg.get_setting("onboarding", "complete")),
        "candidate": display_order()[0].alias,
        "hotkeys": {
            "start": cfg.get_setting("hotkey", "start_recording_hotkey") or "",
            "stop": cfg.get_setting("hotkey", "stop_recording_hotkey") or "",
        },
    }


@method("firstrun.status")
def status(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return _status(rt)


@method("firstrun.complete")
def complete(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    if not rt.config.get_setting("onboarding", "complete"):
        rt.config.update_user_setting("onboarding", "complete", True)
    return {"complete": True}


@method("firstrun.defer")
def defer(rt: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    reason = params.get("reason")
    rt.first_run_deferred = True
    log.info(
        "First-run setup skipped for this session (%s); it returns on the next "
        "launch while no model is downloaded.",
        reason if reason in ("later", "catalogue") else "later",
        extra={"user_message": True},
    )
    return {"deferred": True}
