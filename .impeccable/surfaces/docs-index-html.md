---
version: 1
slug: "docs-index-html"
primary_target: "docs/index.html"
related_targets: []
---

# Surface brief: docs/index.html (landing page, GitHub Pages)

Scope and mode: whole landing page for Lazy to Text, Persuade. Published from docs/ by .github/workflows/pages.yml. Facts come from README.md and PRODUCT.md, and every figure is identical to README.md.

Audience and job: people who want dictation into any active window without sending audio to a cloud service, and who decide whether to download the Windows or macOS build. Primary action: download the build from the release page. Secondary: read the install notes.

Proof and constraints: real app screenshots from docs/screenshots (en and ru). No claims the repository cannot back: no ratings, no install counts, no telemetry. No third-party requests on load: the font and every image are self-hosted. Dark and light themes.

## Direction contract

THESIS: The page is the dictation itself. The first viewport plays hotkey, speech and pasted text as one motion, so the visitor watches the mechanism before reading about it. It refuses the default arrangement of a feature grid under a download button above a stock screenshot.

OWN-WORLD: the DESIGN.md palette in both themes (Gruvbox ground ladder, accent #83a598, primary text #fbf1c7), Inter, flat surfaces with 1px hairlines and no decorative shadows. Keycaps and the editor window are drawn in the app's own card and input language. The microphone glyph comes from the app's icon set.

STORY: The visitor understands that a hotkey records locally and the text lands in the window that had focus. They believe it because the page shows the real app. They act by downloading the build for their operating system.

FIRST VIEWPORT: left column holds the headline "Press a hotkey, speak, paste.", one sentence, and the primary download button (platform-detected, with the other system as a text link). Right column is an editor window with a keycap row above it; a waveform strip runs once, then a sample sentence types into the window. The caption says the sample is synthetic. The primary action sits bottom-left at the fold.

FORM: a mechanism sequence in one horizontal rail of three keycap steps (press, speak, paste) below the fold, then the real screenshots as proof. The user chose this structure from three grounded candidates through the structured question tool. No dice roll was run, so the seed key is none.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
