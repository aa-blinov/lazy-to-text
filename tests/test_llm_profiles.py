"""Profiles: what a bundle is, and what a dictation resolves to.

Two things are worth more than the rest and both are invisible from the
call site. The first is that a config written before profiles existed
must still work, which is why every reading path falls back to the flat
keys rather than raising or returning nothing. The second is that the
per-dictation override must never make a dictation fail: a stale id from
a deleted profile resolves to the active one instead of raising, because
losing someone's words to a stale dropdown is not a trade anybody wants.
"""

from __future__ import annotations

from app.llm import (
    DEFAULT_PROFILE_ID,
    Profile,
    active_profile_id,
    next_profile_id,
    profile_from_mapping,
    profiles_from_config,
    profiles_to_config,
    resolve_profile,
    with_profile,
)

ON = {
    "enabled": True,
    "provider": "ollama",
    "model": "qwen3:8b",
    "base_url": "http://127.0.0.1:11434",
    "api_key": "",
    "mode": "clean",
}


# ---- a config from before profiles -------------------------------------


def test_a_config_without_a_profiles_key_still_resolves():
    """The file is on disk and an older build wrote it. It must load."""
    profile = resolve_profile(ON)

    assert profile.id == DEFAULT_PROFILE_ID
    assert profile.model == "qwen3:8b"
    assert profile.provider == "ollama"


def test_an_entirely_empty_section_still_yields_one_profile():
    """Not zero profiles. Zero means nothing can be selected at all,
    which is worse than picking the one the flat keys describe."""
    profiles = profiles_from_config({})

    assert len(profiles) == 1
    assert profiles[0].id == DEFAULT_PROFILE_ID


def test_the_legacy_profile_keeps_the_flat_api_key():
    """Credentials must survive the shape change, or every user who
    stored one re-authenticates for no stated reason."""
    profiles = profiles_from_config({**ON, "api_key": "sk-secret"})

    assert profiles[0].api_key == "sk-secret"


def test_nothing_is_written_back_to_the_old_file():
    """Reading a legacy config must not rewrite it. The migration here is
    a read-time fallback, not a migration, so the file on disk is
    untouched until the user edits a profile."""
    legacy = dict(ON)
    profiles_from_config(legacy)

    assert "profiles" not in legacy


# ---- resolution --------------------------------------------------------


def test_the_active_profile_is_the_one_named():
    section = {
        "active_profile": "letters",
        "profiles": [
            {"id": "work", "name": "Work"},
            {"id": "letters", "name": "Letters"},
        ],
    }

    assert resolve_profile(section).id == "letters"


def test_an_unknown_active_id_falls_back_to_the_first():
    """The id comes off disk. A config naming a profile this build does
    not have is a settings mismatch, not a crash."""
    section = {
        "active_profile": "deleted",
        "profiles": [{"id": "work", "name": "Work"}],
    }

    assert resolve_profile(section).id == "work"


def test_an_override_wins_over_the_active_profile():
    section = {
        "active_profile": "work",
        "profiles": [
            {"id": "work", "name": "Work"},
            {"id": "letters", "name": "Letters"},
        ],
    }

    assert resolve_profile(section, "letters").id == "letters"


def test_a_stale_override_falls_back_instead_of_raising():
    """The Transcribe picker can hold a profile the user deleted on the
    Profiles screen a moment earlier. The dictation must still run."""
    section = {
        "active_profile": "work",
        "profiles": [{"id": "work", "name": "Work"}],
    }

    assert resolve_profile(section, "deleted").id == "work"


def test_an_empty_override_means_no_override():
    section = {"profiles": [{"id": "work", "name": "Work"}]}

    assert resolve_profile(section, "").id == "work"
    assert resolve_profile(section, "   ").id == "work"


def test_active_profile_id_is_the_first_when_none_is_named():
    section = {"profiles": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]}

    assert active_profile_id(section) == "a"


# ---- the two facts every profile shares --------------------------------


def test_a_custom_prompt_replaces_the_mode():
    profile = Profile(id="p", name="P", mode="clean", custom_prompt="Say hi.")

    assert profile.prompt().startswith("Say hi.")
    assert "Rewrite the dictated text exactly as it was spoken" not in (
        profile.prompt()
    )


def test_a_custom_prompt_still_gets_the_house_rules():
    """The line under the picker promises two things to every reader:
    numbers become digits and nothing is translated. Dropping the rules
    when the user typed their own wording makes that line a lie exactly
    when somebody was paying attention."""
    profile = Profile(
        id="p", name="P", mode="clean", custom_prompt="Only fix commas."
    )
    prompt = profile.prompt()

    assert "digits" in prompt
    assert "language the dictation is in" in prompt


def test_a_blank_custom_prompt_leaves_the_mode_in_charge():
    """Whitespace only. Treating it as a custom prompt would send the
    model an instruction of nothing plus the house rules, which is a
    prompt with no task in it."""
    profile = Profile(
        id="p", name="P", mode="formal", custom_prompt="   \n  "
    )

    assert profile.uses_custom_prompt is False
    assert "formal written prose" in profile.prompt()


def test_a_profile_without_a_custom_prompt_sends_its_mode_verbatim():
    profile = Profile(id="p", name="P", mode="concise")

    assert "short, information-dense version" in profile.prompt()


# ---- endpoints ---------------------------------------------------------


def test_a_cloud_profile_with_no_endpoint_does_not_inherit_loopback():
    """The exact trap ``LLMSettings.from_config`` closes for the flat
    keys: a cloud profile with no address must not send the dictation to
    the user's own machine with an Authorization header attached."""
    profile = Profile(id="p", name="P", provider="openai")

    assert profile.resolved_base_url == "https://api.openai.com/v1"
    assert profile.remote is True


def test_a_local_profile_is_not_remote():
    profile = Profile(id="p", name="P", provider="ollama")

    assert profile.remote is False


# ---- the list as stored ------------------------------------------------


def test_duplicate_ids_keep_the_first_and_drop_the_rest():
    """Ids address profiles from ``active_profile`` and from a saved
    override, so a duplicate makes the second entry unreachable in a way
    nothing on screen reveals."""
    profiles = profiles_from_config({
        "profiles": [
            {"id": "same", "name": "First"},
            {"id": "same", "name": "Second"},
        ],
    })

    assert [p.name for p in profiles] == ["First"]


def test_an_empty_list_falls_back_rather_than_selecting_nothing():
    profiles = profiles_from_config({"profiles": []})

    assert len(profiles) == 1
    assert profiles[0].model == ""


def test_a_profiles_key_that_is_not_a_list_is_ignored():
    profiles = profiles_from_config({"profiles": "oops", **ON})

    assert len(profiles) == 1
    assert profiles[0].model == "qwen3:8b"


def test_profiles_survive_a_round_trip():
    original = profiles_from_config({
        "profiles": [{
            "id": "work",
            "name": "Work",
            "provider": "openrouter",
            "model": "gpt-5.4-mini",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-1",
            "mode": "formal",
            "custom_prompt": "Be brief.",
            "timeout_s": 45,
        }],
    })

    restored = profiles_from_config({"profiles": profiles_to_config(original)})

    assert restored == original


def test_an_entry_that_is_not_a_mapping_still_produces_a_profile():
    profiles = profiles_from_config({"profiles": ["nonsense"]})

    assert len(profiles) == 1
    assert profiles[0].provider == "ollama"


def test_a_junk_timeout_falls_back_rather_than_raising():
    profile = profile_from_mapping({"id": "p", "timeout_s": "fast"})

    assert profile.timeout_s == 20


def test_a_nameless_profile_falls_back_to_its_id():
    """An unnamed row in a dropdown is a row the user cannot refer to."""
    profile = profile_from_mapping({"id": "work"})

    assert profile.name == "work"


# ---- new ids -----------------------------------------------------------


def test_a_new_id_avoids_one_already_taken():
    taken = (Profile(id="profile", name="A"),)

    assert next_profile_id(taken) == "profile2"


def test_a_new_id_never_returns_one_already_taken():
    """Made "work", "work2" and "work3", deleted "work2", pressed New.

    Reusing the gap is the right answer here — "work2" is free, and
    filling a hole is easier to read than a numbering that skips. What
    matters is only that the answer is not taken, because a colliding id
    makes the new profile unreachable *and* silent: the list drops the
    duplicate on the next read and nothing on screen says so.
    """
    taken = (
        Profile(id="work", name="A"),
        Profile(id="work3", name="B"),
    )

    candidate = next_profile_id(taken, base="work")

    assert candidate not in {p.id for p in taken}
    assert candidate == "work2"


def test_a_numbered_id_really_does_not_collide():
    taken = (
        Profile(id="work", name="A"),
        Profile(id="work2", name="B"),
        Profile(id="work3", name="C"),
    )

    assert next_profile_id(taken, base="work") == "work4"


# ---- the mirror back to the flat keys ----------------------------------


def test_the_flat_keys_follow_the_chosen_profile():
    """Settings reads the flat keys, so activating a profile has to move
    them or the two screens would each be right about a different one."""
    section = {"active_profile": "letters", "provider": "ollama"}
    profile = Profile(id="letters", name="Letters", provider="openai", mode="formal")

    flat = with_profile(section, profile)

    assert flat["provider"] == "openai"
    assert flat["mode"] == "formal"


def test_the_mirror_does_not_touch_the_master_switch():
    """Two profiles disagreeing about whether post-processing runs is a
    setting with no answer, so the switch is not part of a profile."""
    section = {"enabled": True, "provider": "ollama"}
    profile = Profile(id="p", name="P", provider="openai")

    flat = with_profile(section, profile)

    assert flat.get("enabled", True) is True

# ---- credentials at the log boundary -----------------------------------


def test_a_saved_profile_never_reaches_the_log_with_its_key():
    """The redaction table matches on section+key, which is exact for a
    key sitting directly in its section. ``llm.profiles`` is a list of
    dicts, so saving a profile missed the table entirely and a plain
    ``repr`` wrote every credential in every profile into ``app.log`` —
    a file the Logs view surfaces."""
    from app.config_manager import _redact_for_log

    stored = profiles_to_config(
        (
            Profile(
                id="letters",
                name="Letters",
                provider="openai",
                model="gpt-5.4-mini",
                api_key="sk-do-not-log-me",
            ),
        )
    )

    rendered = _redact_for_log("llm", "profiles", stored)

    assert "sk-do-not-log-me" not in rendered
    # Structure survives, or the change log is unreadable.
    assert "<set>" in rendered
    assert "gpt-5.4-mini" in rendered


def test_a_secret_key_is_found_at_any_depth():
    from app.config_manager import _redact_for_log

    rendered = _redact_for_log(
        "llm", "profiles", [{"a": {"b": {"api_key": "sk-deep"}}}]
    )

    assert "sk-deep" not in rendered


def test_a_non_secret_field_is_left_alone():
    from app.config_manager import _redact_for_log

    rendered = _redact_for_log("whisper", "model", "large-v3")

    assert rendered == "'large-v3'"
