"""The release workflow publishes one product from one job.

The Qt jobs are gone, so the Electron job is the only publisher: it creates
the GitHub release for a ``v*`` tag, with the changelog section as the body,
and attaches the installers of every platform. These tests hold the shape
that keeps that safe: one writer, built installers first, a body that cannot
be empty, actions pinned by SHA.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _release() -> dict:
    return yaml.safe_load((_WORKFLOWS / "release.yml").read_text(encoding="utf-8"))


def test_the_workflow_has_one_build_and_one_publisher():
    assert set(_release()["jobs"]) == {"desktop", "release"}


def test_the_default_token_is_read_only_and_only_the_publisher_writes():
    wf = _release()
    assert wf["permissions"] == {"contents": "read"}
    writers = [name for name, job in wf["jobs"].items()
               if job.get("permissions", {}).get("contents") == "write"]
    assert writers == ["release"]


def test_the_publisher_waits_for_the_installers_and_only_runs_for_tags():
    job = _release()["jobs"]["release"]
    assert job["needs"] == "desktop"
    assert "refs/tags/v" in job["if"]


def test_the_release_body_is_the_changelog_section_and_is_not_empty():
    steps = _release()["jobs"]["release"]["steps"]
    notes = next(s for s in steps if "CHANGELOG.md" in s.get("run", ""))
    assert "release-notes.md" in notes["run"]
    assert "exit 1" in notes["run"], "a tag with no changelog section must fail before publishing"
    publish = next(s for s in steps if "action-gh-release" in s.get("uses", ""))
    assert publish["with"]["body_path"] == "release-notes.md"
    assert publish["with"]["fail_on_unmatched_files"] is True
    assert publish["with"]["files"] == "desktop-dist/*"


def test_the_tag_is_checked_against_both_version_files():
    steps = _release()["jobs"]["release"]["steps"]
    check = next(s for s in steps if "desktop/package.json" in s.get("run", ""))
    assert "pyproject.toml" in check["run"]
    assert "GITHUB_REF_NAME" in check["run"]


def test_every_third_party_action_is_pinned_by_sha_or_is_first_party():
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        for use in re.findall(r"uses:\s*(\S+)", path.read_text(encoding="utf-8")):
            if use.startswith("./") or use.startswith(("actions/", "github/")):
                continue
            assert re.search(r"@[0-9a-f]{40}$", use), f"{path.name}: {use} is not pinned by SHA"


def test_no_workflow_still_carries_the_qt_environment():
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert "QT_QPA_PLATFORM" not in text, path.name
        assert "libegl1" not in text, path.name


# ---- a release can be checked, because the installers are not signed ----------


def _release_steps() -> list:
    return _release()["jobs"]["release"]["steps"]


def test_the_publisher_alone_may_sign_an_attestation():
    wf = _release()
    assert wf["permissions"] == {"contents": "read"}
    for name, job in wf["jobs"].items():
        perms = job.get("permissions", {})
        has_attest = perms.get("id-token") == "write" and perms.get("attestations") == "write"
        assert has_attest == (name == "release"), name


def test_the_sums_and_the_attestation_come_before_the_installers_are_published():
    steps = _release_steps()
    names = [s.get("name", s.get("uses", "")) for s in steps]
    sums = names.index("Write SHA256SUMS.txt")
    attest = names.index("Attest the build")
    note = names.index("Add the install note to the release notes")
    publish = next(i for i, s in enumerate(steps) if "action-gh-release" in s.get("uses", ""))
    download = names.index("Download the installers")
    assert download < sums < attest < publish
    assert note < publish


def test_the_attestation_covers_every_installer_and_the_sums_file():
    steps = _release_steps()
    attest = next(s for s in steps if s.get("name") == "Attest the build")
    assert attest["uses"].startswith("actions/attest@")
    assert attest["with"]["subject-path"] == "desktop-dist/*"
    sums = next(s for s in steps if s.get("name") == "Write SHA256SUMS.txt")
    assert sums["working-directory"] == "desktop-dist"
    assert "SHA256SUMS.txt" in sums["run"]


def test_the_release_note_points_at_the_install_guide_that_exists():
    steps = _release_steps()
    note = next(s for s in steps if s.get("name") == "Add the install note to the release notes")
    root = Path(__file__).resolve().parents[1]
    for guide in ("docs/INSTALL.md", "docs/INSTALL.ru.md"):
        assert guide in note["run"]
        assert (root / guide).is_file(), guide
    assert "gh attestation verify" in note["run"]
    assert "SHA256SUMS.txt" in note["run"]


def test_the_guide_has_the_sections_the_release_note_links_to():
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    for heading in ("## macOS", "## Windows", "## Linux"):
        assert re.search(rf"^{re.escape(heading)}$", text, re.M), heading
    for needle in ("Open Anyway", "Run anyway", "SHA256SUMS.txt", "gh attestation verify", "chmod +x"):
        assert needle in text, needle


def test_the_russian_guide_covers_the_same_ground():
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs" / "INSTALL.ru.md").read_text(encoding="utf-8")
    for needle in ("Всё равно открыть", "Выполнить в любом случае", "SHA256SUMS.txt",
                   "gh attestation verify", "chmod +x", "xattr"):
        assert needle in text, needle


def test_the_readme_no_longer_promises_a_right_click_that_macos_removed():
    root = Path(__file__).resolve().parents[1]
    text = (root / "README.md").read_text(encoding="utf-8")
    assert "right-click on the app" not in text
    assert "docs/INSTALL.md" in text
