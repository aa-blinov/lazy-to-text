# Specifications

Specifications for Lazy to Text, kept in the GitHub Spec Kit layout. The
rules every spec answers to are in `.specify/memory/constitution.md`.

Specs 001 to 009 are **baseline specs**: they describe what the application
already does, written from the code. Their status is `Implemented
(baseline)`. They were written against the former Qt interface, which spec 011
removed; the Electron interface (spec 010) replaced it, and their behavioural
content is the behaviour spec of the engine. They are the starting point for every new feature.

## Index

| ID | Capability | Status | Link |
| --- | --- | --- | --- |
| 001 | Dictation pipeline: hotkeys, recording, transcription, delivery | Implemented (baseline) | [001-dictation-pipeline](001-dictation-pipeline/spec.md) |
| 002 | Model management: catalogue, download, select, inference settings, first run | Implemented (baseline) | [002-model-management](002-model-management/spec.md) |
| 003 | File transcription: the Transcribe view | Implemented (baseline) | [003-file-transcription](003-file-transcription/spec.md) |
| 004 | History: storage, view, export, clear | Implemented (baseline) | [004-history](004-history/spec.md) |
| 005 | LLM post-processing: presets, providers, fallback contract | Implemented (baseline) | [005-llm-post-processing](005-llm-post-processing/spec.md) |
| 006 | Settings and permissions | Implemented (baseline) | [006-settings-and-permissions](006-settings-and-permissions/spec.md) |
| 007 | Overlay, tray and window | Implemented (baseline) | [007-overlay-tray-window](007-overlay-tray-window/spec.md) |
| 008 | Diagnostics: logs, redaction, crash survival | Implemented (baseline) | [008-diagnostics](008-diagnostics/spec.md) |
| 009 | Packaging and release | Implemented (baseline) | [009-packaging-and-release](009-packaging-and-release/spec.md) |
| 010 | Electron interface on @monos/ui | Implemented (macOS verified; Windows and Linux built by CI) | [010-electron-interface](010-electron-interface/spec.md) |
| 011 | Remove the Qt interface and the CUDA build | Implemented (uncommitted, awaiting review) | [011-remove-qt-interface](011-remove-qt-interface/spec.md) |
| 012 | Speaker diarization for files | Implemented | [012-file-diarization](012-file-diarization/spec.md) |

See also [backlog.md](backlog.md): inconsistencies found while writing the baseline specs, each a candidate for its own spec.

## How features are driven from now on

1. **Specify.** `/speckit-specify` writes a new `specs/NNN-name/spec.md`
   describing what and why, never how. The next free number is taken from
   the table above.
2. **Clarify.** `/speckit-clarify` resolves every `[NEEDS CLARIFICATION]`
   marker and any user-visible ambiguity before planning starts.
3. **Plan.** `/speckit-plan` produces the design. Its Constitution Check
   must pass, or the justified exception goes into Complexity Tracking.
4. **Tasks.** `/speckit-tasks` breaks the plan into ordered, testable tasks.
5. **Implement.** `/speckit-implement` builds the tasks. Tests for a
   behaviour land in the same change as the behaviour.

Two rules keep this honest:

- **The constitution is checked at plan time and again at review.** A
  deviation is written down, not left implicit.
- **Baseline specs stay true.** A change to behaviour that a baseline spec
  describes changes that spec in the same pull request: edit the affected
  requirements, the "Where it lives" section and the tests it names. A
  spec that disagrees with the code is a defect in one of them.

Where a baseline spec records an inconsistency in the code, it is marked
`[NEEDS CLARIFICATION]` or listed under Assumptions rather than silently
fixed; deciding which side is right is a clarify step.
