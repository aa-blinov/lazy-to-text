# Lazy to Text Constitution

The rules every feature, spec and change in this repository answers to.
They are distilled from what this project has already paid for: each one
exists because breaking it once cost a rebuild, a release or a user's
words. `CLAUDE.md` and `AGENTS.md` hold the operational detail; this file
holds the principles a spec is checked against.

## Core Principles

### I. Local-First, Privacy by Default

Speech recognition runs on the user's machine through one ONNX inference
path. Audio never leaves the machine. The one optional step that can reach
a network, post-processing by a language model, is off by default, defaults
to a loopback address, and says in words when it would send the user's
dictation elsewhere. Neither the user's words nor a credential may be
written to `app.log`; the Logs view may show what was just recognised, the
file may not.

### II. A Dictation Never Loses the User's Words

The contract of a dictation tool is that the words reach the window. An
optional feature that fails (a model that is offline, a timeout, a bad
reply) delivers the original text and says so; it never swallows it. A
failure is nameable: it is reported as what it was, not flattened into
"no speech detected". An empty or unusable reply is a failure, never a
silent pass-through of empty text.

### III. Measured, Not Claimed

A number in a model card, a README or a spec comes from a measurement that
can be repeated, with its sample size and its limits stated. Gaps inside
the noise are not reported as differences. A comment does not quote a
measured figure; it points at where the figure is published. A test that
has never been shown failing is not evidence, so a fix is accompanied by a
test that fails without it.

### IV. Platform Honesty

Windows, macOS and Linux are different platforms, and the offscreen test
platform agrees with none of them in the places that matter (layout
defaults, window management, permissions). Platform-specific code is
guarded by the platform conditional that scopes it, Qt properties are named
rather than read back, and a claim about how something looks or behaves on
a platform is taken on that platform. A green offscreen run proves the
plumbing, not the pixels.

### V. Tests Hold the Artifact, and the Suite Is Safe to Run

The suite runs in a scratch home and never touches a user's models, hub
cache, config or lock. No test loads a model; model claims are measured by
hand against the real backend. Skips are platform conditionals or opt-ins,
never a missing dependency, and the counts have to add up across every CI
leg. A release is built from the locked dependency set (`--frozen`), not a
fresh resolution.

### VI. Signed, Hardened, Verified Before Shipping

A build that exits 0 is not a build that is safe to ship. The designated
requirement, the hardened runtime, the entitlements and the seal are read
back and checked, and a build that cannot verify is refused. Work-arounds
that weaken a protection on the shipped artifact to make a local build
pass are not accepted.

### VII. Small Surface, Stated Reasons

A dependency is added only when it justifies its size and platform wheels;
the standard library is preferred when it suffices. A new setting is stored
in `DEFAULT_CONFIG`, never in a tracked file. Comments explain why, never
what. There are no emojis in sources or interfaces, and no literal
colours outside the design tokens.

### VIII. Spec-Driven Changes

A feature starts as a specification under `specs/`, becomes a plan, then
tasks, then code, in that order, and the spec is kept true afterwards. The
baseline specs describe what the application already does; a change to
that behaviour changes the spec in the same pull request. A spec states
what and why, not how; the how belongs to the plan.

## Additional Constraints

- **Interfaces.** The Qt interface and the Electron interface are two front
  ends over one domain stack (`ConfigManager`, `StateManager`, the backend,
  the hotkey listener, the clipboard manager). Behaviour lives in the stack,
  not in either front end, and neither front end may implement a rule the
  other would have to re-learn. Every feature in the Qt interface is either
  present in the Electron interface or recorded in its spec as a deliberate
  omission.
- **Design system.** The Electron interface is built on `@monos/ui`:
  tokens and components from the kit, no colour or radius invented in the
  application.
- **Data.** `config.yaml` is generated, not tracked. User data lives in the
  per-user directories recorded in `CLAUDE.md`; nothing writes into the
  installation directory.
- **Releases.** A version is declared in `pyproject.toml`, `setup.py` and
  `app/version.py` together and matches the newest `v*` tag.

## Development Workflow

1. `/speckit-specify` the feature, then `/speckit-clarify` if anything
   user-visible is ambiguous.
2. `/speckit-plan` against this constitution; the plan's Constitution Check
   must pass or record the justified exception.
3. `/speckit-tasks`, then `/speckit-implement`. Tests for a behaviour land in
   the same change as the behaviour.
4. Before a release: the full suite, the platform checks that apply, and the
   spec status updated.

## Governance

This constitution supersedes habit and convenience. An amendment is a pull
request that states which principle changes and why, and updates the
affected specs and templates in the same change. Reviews check a change
against these principles; a justified deviation is written into the plan's
Complexity Tracking table, not left implicit.

**Version**: 1.0.0 | **Ratified**: 2026-10-24 | **Last Amended**: 2026-10-24
