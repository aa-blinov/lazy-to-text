# QA guide: the Electron interface before it ships to users

Goal: find what a user would hit. Test the application as a hostile, impatient
and careless user would, on top of the happy path. Each QA area is owned by
one tester, who writes `qa/<area>.md`; a developer later fixes by ID.

## What a good defect report is

One entry per defect, in this shape:

```
### QA-<AREA>-<n>  <short title>
Severity: S1 | S2 | S3 | S4
Where: screen / module / file:line
Steps: numbered, exact (inputs, order, timing)
Expected: what the spec or common sense says
Actual: what happened (error text, screenshot path, log line)
Evidence: command output, test, or screenshot file (under qa/evidence/)
Suspected cause: optional, one line
```

Severity: **S1** loses or leaks the user's words or a credential, corrupts
data, crashes or hangs the app, makes the main path (hotkey, record,
transcribe, paste) unusable, or blocks install/first run. **S2** a feature
does not work or gives a wrong answer, a destructive action without a
confirmation, a state that cannot be left. **S3** wrong, misleading or
untranslated text, a layout break, a missing empty/loading/error state, a
keyboard or accessibility failure. **S4** polish.

Report only what you reproduced. Say how many times. Do not pad: five
verified defects beat thirty guesses. List separately what you checked and
found fine, so a reader knows the coverage (`## Covered, no defect`), and what
you could not test (`## Not tested, and why`).

## Method

- The Qt application is the reference for behaviour (specs `001` to `009`);
  the Electron spec is `spec.md` and the parity files in this folder.
- Real runtime, real data, real files wherever you can. Fakes only where the
  environment forces them, and say so.
- Run your own runtime and Vite on your own ports (see
  `../implementation-guide.md`, section 8); use your own scratch directory
  for the config, history and models. Never use the repository's
  `config.yaml`. Never download a model; the small `vosk-ru-small` is in
  `models/hub/models--alphacep--vosk-model-small-ru` (copy it into your
  scratch cache if you need a loaded model). Synthesise speech with
  `say -v Milena -o x.aiff "..."` then `afconvert -f WAVE -d LEI16@16000`.
- Do not fix anything. Do not edit source files. Do not run `git commit`,
  `git stash` or anything that changes git state. Write only under
  `specs/010-electron-interface/qa/`.
- Leave nothing running: stop every process you start.
- The user's real application is installed in /Applications and uses the
  user's real profile. Do not launch it and do not touch the real profile.

## For the developer fixing defects

- Fix by ID, S1 first, then S2, then S3; S4 when cheap. Every fix gets a
  regression test that fails without it (runtime: `tests/server/` or the
  matching top-level `tests/test_*.py`; renderer: `desktop/tests/`; shell:
  `tests/test_desktop_packaging.py` or a new test reading the config) and the
  QA repro is re-run by hand afterwards.
- Under each defect in the QA file add a line `Status: FIXED - <what changed,
  files>; verified by <test name and the repro re-run>`, or `Status: WON'T FIX -
  <reason>`, or `Status: NEEDS <other area> - <what>`. Never mark FIXED without
  running the repro.
- Keep every suite green: `QT_QPA_PLATFORM=offscreen uv run --frozen python -m
  pytest tests/ -n auto -m "not timing" -q` and, in `desktop/`, `npx vitest run`.
  Do not weaken a test to make a change pass.
- Touch only your area's files. If a fix needs a change in another area, mark
  it NEEDS and say exactly what; do not edit the other area.
- No `git commit`, no `git stash`, no state-changing git commands. Leave
  nothing running.

## For the tester re-testing after the fixes

You are a different engineer from the one who wrote the report: do not trust
a `Status: FIXED` line, re-run the original repro by hand against the current
code and record the result as `Retest: PASS | FAIL | NOT RE-TESTED (why)` in
`qa/<area>-retest.md` (one line per defect ID, with the evidence). Then spend
the rest of your effort on what the fixes may have broken (regressions near
each changed file, the contract changes listed by the developers) and on any
new defect, using the same defect format with IDs `QA-<AREA>-R<n>`. A fix
that only works because the test was written around it is a FAIL. The same
rules as before apply (own ports, own scratch directories and Electron
profile, nothing real touched, nothing left running, no source edits).
Ports: runtime=18301/18302/18303/18304/18305 and vite=5601..5605 for
runtime/visual/journeys/shell/security respectively.

## Final round (round three)

Ports: runtime=18501 (runtime), 18502 (visual), 18503 (journeys), 18504
(shell), 18505 (security); vite=5801..5805 in the same order. Start the dev
runtime with `--dev --dev-port <vite>` and `--data-dir <your scratch>` (see
implementation-guide.md rule 8) so config, logs and history are yours alone.
The packaged app is rebuilt by a script: wait for
`/private/tmp/claude-501/rebuild.done` to contain `OK` (an until-loop with
`sleep 20`; `FAIL ...` means report it as defect 1). Kill only the PIDs you
start. Write `qa/<area>-final.md`: a table with every ID of the area (original
and retest IDs) and PASS/FAIL, then new defects as `QA-<AREA>-F<n>`.
Do not repeat what the earlier retest already passed unless the code under it
changed; prioritise the failed and new ones, then regressions.
