# Tasks: Remove the Qt Interface

- [x] T001 Write this spec, plan and tasks; add the index row; add the note to specs 001 to 009.
- [x] T002 Move `recording_factory` and `mic_check` out of `app/gui`; fix importers.
- [x] T003 Translations: merge, `scripts/check_translations.py`, `tests/test_translations.py`, delete `.ts`, `.qm`, `language.py`, export and update scripts.
- [x] T004 Delete `app/gui`, `resource_monitor.py`, Qt packaging files, installer, CUDA code.
- [x] T005 Delete Qt tests, re-home Qt-free tests, trim `tests/conftest.py`, retarget `tests/test_version.py`.
- [x] T006 `pyproject.toml`: drop Qt dependencies and scripts, add `lazy-to-text-server`; `uv lock`; `uv sync --frozen`.
- [x] T007 Workflows: `tests.yml`, `release.yml`; validate YAML.
- [x] T008 Docs: README, CLAUDE.md, AGENTS.md, CONTRIBUTING, DESIGN, PRODUCT, docs/, constitution 1.1.0, CHANGELOG.
- [x] T009 Verify: suite, runtime import without PySide6, `build_server.py` smoke run, grep for leftovers.
