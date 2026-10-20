"""Named bundles of post-processing settings, and the one in use.

A profile is what a person switches between. It carries the five things
that are always changed together — provider, endpoint, model, credential
and mode — plus an optional prompt of their own, because "Clean up" is
the right answer until it is not, and a user who dictates three kinds of
thing in a day wants three answers rather than editing one five-field
form before every session.

Deliberately *not* carrying ``enabled``. That is the master switch above
every profile, and a per-profile copy would mean two profiles disagree
about whether post-processing happens at all — which is the one setting
the user thinks of as a property of the app.

Compatibility is the reason the flat keys stay. ``config.yaml`` before
profiles held ``provider``/``model``/``base_url``/``api_key``/``mode``
directly under ``llm``, and it is a file on disk that an older build
wrote. A missing ``profiles`` list therefore means *one implicit
profile built from those keys*, not *no profiles* — so nothing has to
migrate, and a config written by a build from before this module loads
and keeps working. The list is additive; the old keys remain the
fallback rather than being rewritten away.

Nothing here reaches for the network or touches Qt. A profile is a value
read off disk, which is what lets the same resolution serve the
dictation pipeline, the Settings card and the Transcribe picker without
any of them knowing how the other two work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.llm.client import DEFAULT_TIMEOUT_S
from app.llm.modes import DEFAULT_MODE, _HOUSE_RULES, mode_by_id
from app.llm.providers import PROVIDER_OLLAMA, default_url_for, is_local_url

#: The id of the profile a fresh install has, and the one an older
#: config's flat settings become. Deliberately not a generated id: the
#: file is read by people, and "default" is what they will expect to
#: find in it.
DEFAULT_PROFILE_ID = "default"

#: The name shown for that profile. Also what a config-less install
#: calls the implicit profile it builds from the flat keys.
DEFAULT_PROFILE_NAME = "Default"


@dataclass(frozen=True)
class Profile:
    """One bundle of post-processing settings.

    Frozen for the same reason :class:`~app.llm.client.LLMSettings` is:
    this value is handed to the dictation pipeline and read there, and a
    settings screen that kept mutating it underneath would make "what
    did this dictation actually use" unanswerable.
    """

    id: str
    name: str
    provider: str = PROVIDER_OLLAMA
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    mode: str = DEFAULT_MODE
    custom_prompt: str = ""
    timeout_s: int = 20

    @property
    def uses_custom_prompt(self) -> bool:
        """Whether ``custom_prompt`` is in charge of the wording."""
        return bool(self.custom_prompt.strip())

    @property
    def resolved_base_url(self) -> str:
        """The endpoint, resolved against the chosen provider.

        Empty means "whatever this provider defaults to", rather than
        inheriting loopback — a cloud profile with no endpoint must not
        send the dictation back to the user's own machine with the
        Authorization header attached.
        """
        return self.base_url.strip() or default_url_for(self.provider)

    @property
    def remote(self) -> bool:
        """Whether words leave this machine on this profile's settings."""
        return not is_local_url(self.resolved_base_url)

    def prompt(self) -> str:
        """The system prompt this profile sends.

        A user's own prompt still gets ``_HOUSE_RULES`` appended, and
        that is not a courtesy. The shared line under the picker tells
        every user that numbers become digits and that nothing is
        translated — those are promises the app makes, not suggestions
        the mode makes. Dropping the rules whenever the user typed their
        own wording would make that line a lie exactly when somebody was
        paying attention.
        """
        if self.uses_custom_prompt:
            return f"{self.custom_prompt.strip()}{_HOUSE_RULES}"
        return mode_by_id(self.mode).prompt


def _text(value: Any, fallback: str = "") -> str:
    """A string field that tolerates ``None`` and non-strings."""
    if value is None:
        return fallback
    if isinstance(value, str):
        return value
    return str(value)


def _positive_int(value: Any, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def profile_from_mapping(raw: Any, fallback_id: str = DEFAULT_PROFILE_ID) -> Profile:
    """Build one profile from a config entry, tolerating junk.

    A value of the wrong type falls back rather than raising, on the
    same reasoning as :meth:`LLMSettings.from_config`: this is a
    dictation tool, and a hand-edited config with ``timeout_s: "fast"``
    must not stop someone's speech from reaching the window.
    """
    data = raw if isinstance(raw, dict) else {}

    provider = _text(data.get("provider")).strip() or PROVIDER_OLLAMA
    name = _text(data.get("name")).strip()
    identifier = _text(data.get("id")).strip() or fallback_id

    return Profile(
        id=identifier,
        # A profile with no name is still selectable; falling back to
        # its id means the picker shows something the user can refer to
        # instead of an empty row.
        name=name or identifier,
        provider=provider,
        model=_text(data.get("model")).strip(),
        base_url=_text(data.get("base_url")).strip(),
        api_key=_text(data.get("api_key")),
        mode=_text(data.get("mode")).strip() or DEFAULT_MODE,
        custom_prompt=_text(data.get("custom_prompt")),
        timeout_s=_positive_int(data.get("timeout_s"), DEFAULT_TIMEOUT_S),
    )


def profile_from_legacy(section: dict[str, Any]) -> Profile:
    """The one implicit profile a pre-profiles config describes.

    Not a migration — nothing is written back. This runs on every read,
    so a config that predates profiles and a fresh install with no
    ``profiles`` key resolve to the same thing without either having
    been touched.
    """
    return profile_from_mapping(
        {
            "id": DEFAULT_PROFILE_ID,
            "name": DEFAULT_PROFILE_NAME,
            "provider": section.get("provider"),
            "model": section.get("model"),
            "base_url": section.get("base_url"),
            "api_key": section.get("api_key"),
            "mode": section.get("mode"),
            "timeout_s": section.get("timeout_s"),
        }
    )


def profiles_from_config(section: dict[str, Any] | None) -> tuple[Profile, ...]:
    """Every profile in the ``llm`` section, at least one.

    Falling back to the legacy profile rather than returning an empty
    tuple means no caller has to handle "no profiles" — the same reason
    :func:`mode_by_id` falls back to the default mode. An empty list
    would mean nothing can be selected at all, which is a worse outcome
    than picking the one the flat keys describe.
    """
    section = section or {}
    raw = section.get("profiles")
    if not isinstance(raw, list):
        return (profile_from_legacy(section),)

    built: list[Profile] = []
    for index, entry in enumerate(raw):
        profile = profile_from_mapping(entry, fallback_id=f"profile{index + 1}")
        # Ids address profiles from ``active_profile`` and from a saved
        # per-dictation override, so a duplicate makes the second entry
        # unreachable in a way nothing on screen would reveal. First one
        # wins, matching how a dict would behave and never raising.
        if any(existing.id == profile.id for existing in built):
            continue
        built.append(profile)

    return tuple(built) or (profile_from_legacy(section),)


def active_profile_id(section: dict[str, Any] | None) -> str:
    """Which profile a dictation uses when nothing overrides it."""
    section = section or {}
    profiles = profiles_from_config(section)
    wanted = _text(section.get("active_profile")).strip()
    if wanted and any(p.id == wanted for p in profiles):
        return wanted
    return profiles[0].id


def resolve_profile(
    section: dict[str, Any] | None,
    override_id: str = "",
) -> Profile:
    """The profile to run, given a per-dictation override.

    An override naming a profile that does not exist falls back to the
    active one rather than failing the dictation. The override arrives
    from the Transcribe picker and can be stale — a profile deleted on
    the Profiles screen while the picker still held its id — and losing
    a dictation to a stale dropdown is not a trade anybody wants.
    """
    profiles = profiles_from_config(section)
    override_id = override_id.strip()
    if override_id:
        for profile in profiles:
            if profile.id == override_id:
                return profile
    wanted = active_profile_id(section)
    for profile in profiles:
        if profile.id == wanted:
            return profile
    return profiles[0]


def profiles_to_config(profiles: tuple[Profile, ...]) -> list[dict[str, Any]]:
    """Serialise back to plain YAML-safe dicts.

    Every field is written, including the empty ones. A profile that
    stops carrying its (empty) key is indistinguishable from one whose
    key some other code removed, and this file is read by hand.
    """
    return [
        {
            "id": p.id,
            "name": p.name,
            "provider": p.provider,
            "model": p.model,
            "base_url": p.base_url,
            "api_key": p.api_key,
            "mode": p.mode,
            "custom_prompt": p.custom_prompt,
            "timeout_s": p.timeout_s,
        }
        for p in profiles
    ]


def with_profile(section: dict[str, Any], profile: Profile) -> dict[str, Any]:
    """A copy of *section* whose flat keys match *profile*.

    Used when one is chosen as the active one, so the Settings card and
    the pre-profiles code paths keep agreeing with the profile list
    instead of the two drifting into separate truths.
    """
    updated = dict(section or {})
    updated.update(
        {
            "provider": profile.provider,
            "model": profile.model,
            "base_url": profile.base_url,
            "api_key": profile.api_key,
            "mode": profile.mode,
            "timeout_s": profile.timeout_s,
        }
    )
    return updated


def next_profile_id(profiles: tuple[Profile, ...], base: str = "profile") -> str:
    """An id not already taken.

    Numbered rather than random so the file stays readable, and checked
    rather than assumed because a user who made "work", "work2" and
    "work3", deleted "work2", and then pressed New must get "work4" and
    not a collision that silently drops the new profile.
    """
    taken = {p.id for p in profiles}
    if base not in taken:
        return base
    index = 2
    while f"{base}{index}" in taken:
        index += 1
    return f"{base}{index}"


__all__ = [
    "DEFAULT_PROFILE_ID",
    "DEFAULT_PROFILE_NAME",
    "Profile",
    "active_profile_id",
    "next_profile_id",
    "profile_from_legacy",
    "profile_from_mapping",
    "profiles_from_config",
    "profiles_to_config",
    "resolve_profile",
    "with_profile",
]
