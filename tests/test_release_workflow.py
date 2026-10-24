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
