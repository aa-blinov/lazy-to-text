"""What ``config.yaml`` must never give away, and must never destroy.

Four separate promises about one file:

* the Hugging Face token does not get logged, in either direction;
* the file itself is not world-readable;
* a hand-edit that breaks the YAML is moved aside rather than
  overwritten by defaults;
* the ``history`` section advertises only retention the app performs.

The first three are about the credential, which is the only thing in
this file worth stealing — so they are tested together, and the last
one is here because it is the same file and the same kind of claim:
a key in ``DEFAULT_CONFIG`` is a promise the UI makes to the user.
"""

from __future__ import annotations

import copy
import logging
import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_config_manager import fake_project  # noqa: F401  (fixture)


# Reused isolation, not reinvented: ``fake_project`` chdir's into a tmp
# dir holding a ``pyproject.toml`` so ``_resolve_base_dir``'s walk stops
# there instead of climbing to the real repo root and writing over the
# developer's ``config.yaml``. Imported rather than duplicated so this
# file cannot drift into a second, weaker version of it.

SECRET_FIRST = "hf_firstSecretValue"
SECRET_SECOND = "hf_secondSecretValue"


# ---- 1. the token stays out of the log --------------------------------------


def _set(caplog, cm, section, key, value):
    """``update_user_setting`` with the log cleared around the call."""
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.config_manager"):
        cm.update_user_setting(section, key, value)
    return caplog.records


def _logged_text(records) -> str:
    """Every record's rendered message — what actually reaches a log file."""
    return "\n".join(r.getMessage() for r in records)


def test_a_hf_token_is_never_logged_in_either_direction(caplog, fake_project):
    """Two writes in a row, so the token is the *old* value and the
    *new* value across the pair — the "Clear token" click is the case
    that used to write the credential out.

    ``update_user_setting`` logs ``old -> new`` for everything it
    writes, and the root logger runs at INFO with a plain FileHandler
    that nothing ever scrubs.
    """
    from app.config_manager import ConfigManager

    cm = ConfigManager()
    cm.update_user_setting("huggingface", "token", SECRET_FIRST)
    cm.flush_pending_writes()

    records = _set(caplog, cm, "huggingface", "token", SECRET_SECOND)
    text = _logged_text(records)

    assert records, "sanity: the setting change should have been logged"
    assert SECRET_SECOND not in text, text
    assert SECRET_FIRST not in text, (
        "the previous token was logged; 'Clear token' would write the "
        "credential it is clearing"
    )


def test_the_token_line_still_names_the_setting(caplog, fake_project):
    """Redaction is not the same as silence.

    A change to the token is worth knowing about — the user changed
    something and wants to see that the app noticed. Only the values
    are secret; ``huggingface.token`` is not.
    """
    from app.config_manager import ConfigManager

    cm = ConfigManager()
    records = _set(caplog, cm, "huggingface", "token", SECRET_FIRST)

    assert records, "sanity: the setting change should have been logged"
    assert "huggingface.token" in _logged_text(records), _logged_text(records)


def test_a_non_secret_setting_still_logs_its_value(caplog, fake_project):
    """The guard against a fix that redacts everything.

    A blanket "log no values" would satisfy the token test and cost
    the setting-change log its only reason to exist, so an ordinary
    setting is asserted to log both of its real values.
    """
    from app.config_manager import ConfigManager

    cm = ConfigManager()
    records = _set(
        caplog, cm, "hotkey", "start_recording_hotkey", "ctrl+alt+shift+k"
    )

    assert records, "sanity: the setting change should have been logged"
    text = _logged_text(records)
    assert "ctrl+alt+shift+k" in text, text
    # The old value too — ``ctrl+f2``/``ctrl+f8`` depending on platform,
    # so assert on the rendered "old -> new" shape rather than a literal.
    assert " -> " in text, text


def test_clearing_the_token_does_not_log_what_it_cleared(caplog, fake_project):
    """The user-facing "Clear token" button sets the value to ``""``.

    That is the one write whose *old* value is the secret and whose
    new value is nothing at all, so it is the write most likely to
    leak it.
    """
    from app.config_manager import ConfigManager

    cm = ConfigManager()
    cm.update_user_setting("huggingface", "token", SECRET_FIRST)
    cm.flush_pending_writes()

    records = _set(caplog, cm, "huggingface", "token", "")
    text = _logged_text(records)

    assert records, "sanity: clearing the token should have been logged"
    assert SECRET_FIRST not in text, text


def test_every_credential_in_the_defaults_is_registered_as_one():
    """Membership, checked against ``DEFAULT_CONFIG`` rather than against
    ``_REDACTED_SETTINGS`` itself.

    The first version of this test iterated the frozenset, which made it
    vacuous in exactly the case it exists for: dropping
    ``("llm", "api_key")`` removed the credential from the set *and* from
    the loop that was supposed to notice, so the test passed with the key
    in plain text in ``app.log``. A test driven by the thing it audits
    cannot fail when that thing shrinks.

    So the expected membership is *derived* — every default key named
    like a credential — and a new one is covered the moment it lands in
    ``DEFAULT_CONFIG``, which is the only moment anybody is thinking
    about it.

    Matched on the whole name, not a substring: ``hotkeys`` carries
    ``push_to_talk_key`` and ``cancel_recording_hotkey``, and a
    substring rule calls both credentials and fails the whole file for
    the wrong reason, which is the fastest way to teach everyone to
    ignore a red build.
    """
    from app.config_manager import DEFAULT_CONFIG, _REDACTED_SETTINGS

    credential_names = {
        "token", "api_key", "apikey", "secret", "password",
        "access_token", "auth_token",
    }
    declared = {
        (section, key)
        for section, values in DEFAULT_CONFIG.items()
        for key in values
        if key.lower() in credential_names
    }

    assert declared, "sanity: DEFAULT_CONFIG still carries a credential"
    assert declared == set(_REDACTED_SETTINGS), (
        "a credential is in DEFAULT_CONFIG but not in _REDACTED_SETTINGS, "
        f"so its value reaches app.log in plain text: "
        f"{sorted(declared - set(_REDACTED_SETTINGS))}"
    )


def test_every_redacted_setting_really_keeps_its_value_out_of_the_log(
    caplog, fake_project
):
    """The behaviour half, over whatever ``_REDACTED_SETTINGS`` holds.

    Membership is the test above; this one proves a registered
    credential is actually kept out of the log in both directions, which
    is the case the "Clear key" button produces and the one that used to
    write the value out.
    """
    from app.config_manager import _REDACTED_SETTINGS, ConfigManager

    assert _REDACTED_SETTINGS, "sanity: there is at least one credential"

    for section, key in sorted(_REDACTED_SETTINGS):
        secret = f"secret-for-{section}-{key}"
        cm = ConfigManager()

        # Two *different* values, so the pair is the secret as both the
        # old and the new value. Writing the same one twice is a no-op
        # that logs nothing, and a test built on it would pass against an
        # unredacted logger.
        records = _set(caplog, cm, section, key, secret)
        records += _set(caplog, cm, section, key, secret + "-rotated")
        records += _set(caplog, cm, section, key, "")
        text = _logged_text(records)

        assert secret not in text, (
            f"{section}.{key} is registered as a credential but its value "
            f"reached the log: {text}"
        )
        assert f"{section}.{key}" in text, (
            "sanity: the change itself should still be logged, only the "
            f"value redacted — {text}"
        )


# ---- 2. the file on disk is owner-only --------------------------------------
#
# The claim is about the *file*, and on POSIX that is a mode. Windows
# has no mode bits to assert — the config dir inherits its ACL instead —
# so these two skip there rather than pretend to have checked.

_SKIP_NO_POSIX_MODE = pytest.mark.skipif(
    sys.platform == "win32",
    reason="no POSIX mode bits on Windows; the config dir carries the ACL",
)


@pytest.fixture
def fixed_umask():
    """Pin the umask to 0o022 for the duration of a test.

    Without this the chmod assertions are only as strong as whatever
    the machine's umask happens to be: on a box running ``umask 077`` a
    build with the ``chmod`` deleted outright writes 0600 anyway and
    the test passes against it. 0o022 is the mode ``open()`` produces
    with the fix removed, which is what makes the two assertions below
    about the ``chmod`` at all.
    """
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


@_SKIP_NO_POSIX_MODE
def test_the_written_config_carries_no_group_or_other_bits(
    fake_project, fixed_umask,
):
    """``config.yaml`` holds the Hugging Face token, and it was written
    at the umask default before anything thought about it."""
    from app.config_manager import ConfigManager

    cm = ConfigManager()
    cm.update_user_setting("huggingface", "token", SECRET_FIRST)
    cm.flush_pending_writes()

    mode = stat.S_IMODE(os.stat(cm.config_path).st_mode)
    assert mode & 0o077 == 0, (
        f"config.yaml is mode {mode:04o}; a 0o600 config is what keeps "
        "the token off every other account on the machine"
    )


@_SKIP_NO_POSIX_MODE
def test_the_staging_file_is_locked_down_before_the_rename(
    fake_project, fixed_umask, monkeypatch,
):
    """Order, not just the final mode.

    ``open()`` has no mode argument for a file that already exists, so
    the staging file is created at the umask default and can only be
    chmod-ed afterwards. Chmod-ing the *target* after ``os.replace``
    would leave a real window where the token is on disk at 0644 —
    and the final-mode assertion above cannot see that window, because
    by the time it runs the mode is correct either way.

    So: record the staging file's mode at the moment ``os.replace`` is
    called.
    """
    from app.config_manager import ConfigManager

    observed: list[tuple[Path, Path, int]] = []
    real_replace = os.replace

    def spy(src, dst):
        observed.append((Path(src), Path(dst), stat.S_IMODE(os.stat(src).st_mode)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    cm = ConfigManager()
    cm.update_user_setting("huggingface", "token", SECRET_FIRST)
    cm.flush_pending_writes()
    monkeypatch.undo()

    assert observed, "sanity: the atomic swap should have been observed"
    for src, dst, mode in observed:
        assert src.name == f"{cm.config_path.name}.tmp", (src, dst)
        assert mode & 0o077 == 0, (
            f"{src} was still mode {mode:04o} at the moment it was "
            f"renamed onto {dst}"
        )


# ---- 3. an unparseable config is quarantined, not erased --------------------

# A tab where YAML wants a space. ``safe_load`` rejects it outright,
# and the file still holds the user's hotkey in plain sight — which is
# what makes it worth keeping.
def _same_bytes(left: bytes, right: bytes) -> bool:
    """Byte equality that ignores line-ending translation.

    ``Path.write_text`` opens in text mode, so the ``\n`` in a literal
    is written as ``\r\n`` on Windows. Asserting on raw bytes then
    fails there for a reason that has nothing to do with what is being
    pinned — the quarantine still preserved the file. This compares what
    the file *says*, not how the platform spelled the line breaks.
    """
    return left.replace(b"\r\n", b"\n") == right.replace(b"\r\n", b"\n")


CORRUPT_CONFIG = (
    "hotkey:\n"
    "  start_recording_hotkey: ctrl+alt+shift+k\n"
    "huggingface:\n"
    "\ttoken: hf_secretInTheCorruptFile\n"
)


def test_an_unparseable_config_is_moved_aside_not_overwritten(
    fake_project, monkeypatch,
):
    """One stray tab used to send the whole file to the bin: defaults
    were written over the top of it, taking the hotkeys, storage path,
    model choice and token with no trace."""
    from app.config_manager import ConfigManager, DEFAULT_CONFIG

    config_path = fake_project / "config.yaml"
    config_path.write_text(CORRUPT_CONFIG, encoding="utf-8")

    # ...and it must not be read back either. A parse failure means we
    # have no idea what is in there, so the quarantined copy is a
    # thing a human sorts out, not something the app tries to salvage.
    reads: list[Path] = []
    real_open = open

    def spy_open(file, *args, **kwargs):
        try:
            name = str(Path(file))
        except TypeError:  # fd, not a path
            name = ""
        if ".corrupt-" in name:
            reads.append(Path(name))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy_open)
    cm = ConfigManager()
    monkeypatch.undo()

    quarantined = fake_project / "config.yaml.corrupt-1"
    assert quarantined.exists(), (
        "the unparseable config was destroyed instead of kept; defaults "
        "were written straight over it"
    )
    assert _same_bytes(quarantined.read_bytes(),
                       CORRUPT_CONFIG.encode("utf-8"))

    # The original path is back, holding fresh defaults and none of the
    # user's data.
    assert config_path.exists()
    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == DEFAULT_CONFIG
    assert cm.config == DEFAULT_CONFIG

    assert reads == [], f"the quarantined file was read back: {reads}"


def test_a_second_corrupt_config_does_not_clobber_the_first(fake_project):
    """The name is numbered, so a second bad load keeps both — the
    first one is often the file the user wants back."""
    from app.config_manager import ConfigManager

    first = "hotkey:\n\tmode: two_keys\n"
    second = "audio:\n\tchannels: 2\n"

    config_path = fake_project / "config.yaml"

    config_path.write_text(first, encoding="utf-8")
    ConfigManager()
    assert _same_bytes((fake_project / "config.yaml.corrupt-1").read_bytes(),
                       first.encode("utf-8"))

    config_path.write_text(second, encoding="utf-8")
    ConfigManager()

    assert _same_bytes((fake_project / "config.yaml.corrupt-1").read_bytes(),
                       first.encode("utf-8")), "the first quarantine was overwritten"
    assert _same_bytes((fake_project / "config.yaml.corrupt-2").read_bytes(),
                       second.encode("utf-8"))


def test_a_quarantined_config_can_be_brought_back_by_hand(fake_project):
    """The recovery the log message promises: *move it back by hand*.

    A file that failed to parse cannot be read back as-is — the user
    repairs the offending line first, and the question this answers
    is whether the quarantined copy was preserved faithfully enough to
    be worth repairing, or whether it arrived already truncated.
    """
    from app.config_manager import ConfigManager

    config_path = fake_project / "config.yaml"
    config_path.write_text(CORRUPT_CONFIG, encoding="utf-8")
    ConfigManager()

    quarantined = fake_project / "config.yaml.corrupt-1"
    repaired = quarantined.read_text(encoding="utf-8").replace("\t", "  ")

    # What the user does: fix it, put it back.
    repaired_path = fake_project / "config.yaml.repaired"
    repaired_path.write_text(repaired, encoding="utf-8")
    repaired_path.replace(config_path)

    cm = ConfigManager()
    assert cm.get_setting("hotkey", "start_recording_hotkey") == "ctrl+alt+shift+k"
    assert cm.get_setting("huggingface", "token") == "hf_secretInTheCorruptFile"


# ---- 4. the retention key that promised a policy nobody performed -----------


def test_history_advertises_only_retention_it_actually_performs():
    """``history.auto_cleanup_days: 30`` was declared in
    ``DEFAULT_CONFIG`` and read by nothing — no consumer in ``app/``,
    no control for it in the UI. A setting that silently promises it
    will erase your dictations is worse than no setting.

    ``max_entries`` is asserted alongside it so this test cannot be
    satisfied by deleting the section instead of the key.
    """
    from app.config_manager import DEFAULT_CONFIG

    history = DEFAULT_CONFIG["history"]

    assert "auto_cleanup_days" not in history, (
        "a retention policy nothing implements is back in the shipped "
        "defaults"
    )
    assert "max_entries" in history, (
        "history bounded by entry count is the policy that is actually "
        "performed; it must stay"
    )


# The module-level default dicts are shared mutable state; a test that
# gets hold of one and writes to it would poison every later test.
@pytest.fixture(autouse=True)
def _restore_default_config():
    from app.config_manager import DEFAULT_CONFIG

    snapshot = copy.deepcopy(DEFAULT_CONFIG)
    yield
    DEFAULT_CONFIG.clear()
    DEFAULT_CONFIG.update(snapshot)