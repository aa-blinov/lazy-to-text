# Lazy to Text: state of the app

Last updated with release 0.1.13. This is a working document for the team: what
is done, what was verified and how, and what is still open. User-facing docs
are README.md and docs/index.html.

## Done

- **Interface languages.** Russian and English, switched live in
  Settings → Appearance → Language. Every screen, tray item, dialog and overlay
  message is translated through `app/i18n/app_ru.ts`; `scripts/update_translations.py`
  keeps the catalogue complete.
- **Post-processing.** One switch and one model configuration on the
  Post-processing screen. Several saved variants sit behind "Several variants…".
- **Models.** Sort by recommended order, accuracy or size; filter by family
  and by language; metric tooltips; descriptions folded to three lines.
- **Layout.** Minimum window 900×600. Below 1000 px the sidebar shows icons only,
  with names in tooltips. Checked at text scale 1.75 in Russian.
- **Overlay and dock.** The recording capsule shows above full-screen windows of
  other apps; the Dock icon follows the main window.
- **Icons.** App icon and tray icons in the DESIGN.md palette.

## Verified

- Test suite: 1492 passed, 10 skipped (main run), plus 8 timing tests run serially.
- Release builds for macOS and Windows; the macOS bundle is signed and verified.
- Screenshots at text scale 1.0 and 1.75, in English and Russian, for every screen.
- Language switch round trip: strings return to English after Russian.

## Not verified

- A full dictation on a live Mac: hotkey → recording → transcription → paste.
  Accessibility permission for the test host was not available.
- Model download and cancel with real downloads.
- Keyboard-only use and VoiceOver.
- Windows layout for the latest changes (only CI ran there).
- The first-run flow at text scale 1.75 end to end.

## Open decisions

- **App icon.** No brand identity document exists; the icon follows the DESIGN.md
  palette the team chose.
- **Names.** Model families, providers and the model alias stay in Latin script.
- **Hotkeys on macOS.** Defaults are ctrl+F8/F9/F10 in code; a user config may
  still hold ctrl+F2/F3/F6 from earlier builds.

## Known limits

- The model list is long: 16 cards. Sorting and filters help, a search by
  language is not a substitute for a shorter default list.
- Automatic update checks do not exist; users learn about a release by hand.
- Some pixel-based and config-file tests are sensitive to parallel runs and
  occasionally fail under `-n auto`; they pass on rerun.
