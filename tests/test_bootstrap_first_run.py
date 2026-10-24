"""Who gets the first-run screen, and what start-up says when there is nothing to load.

``_should_show_first_run`` and ``_autoload_persisted_model`` live in
``app/bootstrap.py`` and are used by the runtime; re-homed from the Qt tests.
"""

from unittest.mock import MagicMock

import pytest




def _config(complete):
    """The one config section first run reads, and nothing else.

    Mirrors the real shape — ``get_setting(section, key)`` over nested
    dicts — rather than answering from a flat bag, so a renamed section
    fails here instead of silently reading ``None``.
    """
    sections = {"onboarding": {"complete": complete}}
    config = MagicMock()
    config.get_setting.side_effect = lambda section, key: sections.get(
        section, {}
    ).get(key)
    return config




# ---- who gets the screen ---------------------------------------------------


def test_a_fresh_install_gets_the_setup_screen():
    from app.bootstrap import _should_show_first_run

    assert _should_show_first_run(_config(False), False)


def test_someone_who_already_downloaded_a_model_never_sees_it_again():
    """The case that decides whether this ships: every existing install
    reads ``complete: False`` out of the defaults because its config
    predates the section, and all of them have weights on disk."""
    from app.bootstrap import _should_show_first_run

    assert _should_show_first_run(
        _config(False), True
    ) is False


def test_a_finished_first_run_is_not_shown_again():
    from app.bootstrap import _should_show_first_run

    assert _should_show_first_run(
        _config(True), False
    ) is False


def test_an_unreadable_config_does_not_wall_the_app_off():
    """A screen the user cannot finish is worse than no screen."""
    from app.bootstrap import _should_show_first_run

    config = MagicMock()
    config.get_setting.side_effect = RuntimeError("no such file")
    assert _should_show_first_run(config, False) is False


def test_startup_says_so_when_there_is_nothing_to_load():
    """This log line was unreachable — it sat inside the fallback loop
    after its own ``return``, so the one case a first-run user is in
    wrote nothing at all."""
    import logging

    from app.bootstrap import _autoload_persisted_model

    backend = MagicMock()
    backend.current_model.return_value = "gigaam-v3-ctc"
    with pytest.MonkeyPatch.context() as mp:
        import app.bootstrap as module

        mp.setattr(module, "is_cached_for_info", lambda info: False)
        mp.setattr(module, "is_model_cached", lambda name: False)
        with __import__("tempfile").TemporaryDirectory() as tmp:
            mp.setenv("LAZY_TO_TEXT_MODELS_DIR", tmp)
            with __import__("io").StringIO() as buf:
                handler = logging.StreamHandler(buf)
                logger = logging.getLogger("app.bootstrap")
                logger.setLevel(logging.INFO)
                logger.addHandler(handler)
                try:
                    found = _autoload_persisted_model(backend, None)
                    # Read inside the block: a StringIO is closed on the
                    # way out, and reading it afterwards is a ValueError
                    # that has nothing to do with what is under test.
                    logged = buf.getvalue()
                finally:
                    logger.removeHandler(handler)
    assert found is False
    assert backend.load.call_count == 0
    # The line itself. It was unreachable for its whole life — it sat
    # inside the fallback loop after its own ``return`` — so the one
    # case a first-run user is in wrote nothing at all, and a test that
    # only checks the return value would have passed against the dead
    # version just as happily.
    assert "skipping auto-load" in logged, logged
