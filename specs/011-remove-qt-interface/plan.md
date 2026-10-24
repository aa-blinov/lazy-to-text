# Implementation Plan: Remove the Qt Interface

Constitution check: principle I to III unaffected (engine untouched). The "two front ends over one engine" constraint is amended to one front end (constitution 1.1.0).

Order matters; each step leaves the tree importable.

1. **Migrate** what the runtime imports out of `app/gui` (`recording_factory`, `mic_check`), update every importer.
2. **Translations**: merge `.ts` entries still referenced into the renderer JSON, add `scripts/check_translations.py` and its test, then delete the Qt catalogue and tooling.
3. **Delete** `app/gui`, Qt wrappers, Qt packaging, CUDA code, installer. Keep `vendor/portaudio`, sounds, signing scripts.
4. **Tests**: delete Qt tests, re-home Qt-free ones, trim `conftest.py`, retarget `test_version.py`.
5. **pyproject and lock**: drop Qt dependencies and scripts, add `lazy-to-text-server`, `uv lock`, commit-ready lock.
6. **Workflows**: remove Qt env and packages from `tests.yml`; `release.yml` keeps one publisher, the Electron job, which creates the release.
7. **Docs**: README, CLAUDE.md, AGENTS.md, CONTRIBUTING, DESIGN/PRODUCT, `docs/`, constitution, changelog, baseline specs note.
8. **Verify** per the acceptance list.

Risks: a Qt-free module quietly importing from `app/gui` (grep proves none remain); tests owned by the 010 developer that still name moved modules (listed, not edited); the frozen runtime losing a data file (the build smoke run proves it).
