# Design system: Lazy to Text

The interface is the Electron app in `desktop/`, built on the
[`@monos/ui`](https://github.com/aa-blinov/monos-ui) kit: warm paper, one 6px
radius, text buttons, six palettes in a light and a dark variant. Colours,
radii, spacing and type sizes are the kit's tokens, and the application
invents none of its own. The tokens live in the kit; this file records what
the product asks of them.

This document replaces the one written for the retired Qt interface (its
fifteen-token Gruvbox stylesheet, the QSS rules and the measurements taken
against Qt widgets). That version is in the git history. What carried over is
the product-level part: how a screen names itself, what an empty state says,
and the rules below.

## Overview

A dictation tool is used with one window of somebody else's document in
focus. The interface never decorates and never asks for attention it has not
earned: the recording state and the loaded model are the only things allowed
to speak up. The text the user is dictating is the point; everything else is
quiet.

- **Flat surfaces, hairlines for structure.** Depth is a background step, not
  an effect. No gradients, no glass, no blur, no emoji.
- **One voice for the accent.** The kit's accent means one thing at a time:
  focus, selection, or the primary action.
- **Text buttons.** A button says what it does in words.
- **Six palettes, light and dark.** The app follows the system appearance;
  Settings can force either and pick a palette. A palette is chosen from the
  kit, never composed in the app, and a light palette is not the dark one
  inverted.
- **A window that shrinks to 900 by 600.** Layout decisions come from the
  space a group has, not from a table of window sizes, so they survive a
  larger text scale.

## Page identity

**Every view names itself.** A title and one line of purpose sit above the
view's controls, built once and used by every screen. Without it Transcribe,
History, Logs and Models read as one long settings panel, because nothing on
screen says which section you are in. The purpose line explains what the
section is *for*, so it has to stay readable: it is secondary ink, never the
muted ink used for hints.

**One primary action per view, and it means something.** An accent-filled
button promises to be the thing to press. A card list is exempt by design:
each card's Download or Select is the primary action *of that card*.

**Destructive actions are marked.** Anything that discards (Clear in History
and Logs, the Hugging Face token reset in Settings) carries the danger role.
Ask a test which buttons claim to destroy something rather than trusting the
eye; a token reset once shipped painted like a neutral control.

## Empty states

An empty state is the screen's job before there is data, not a gap in the
layout. It carries three things: what is missing, why, and what to do, and it
stands on the same surface the content will, because a bare region stops
reading as a surface and becomes a hole in the window. Where the answer is a
key press, the key is a monospaced cap under the sentence rather than part of
it: the most skimmable line on the screen should not look like every other
sentence.

Logs keys its empty state on the *buffer*, not on what survived the filters:
a search matching nothing shows an empty stream, not a claim that the app has
never logged anything.

**Instrument telemetry appears when it has something to say.** A CPU and RAM
meter pinned on every screen, reading 0%, occupies the best position in the
window to say nothing. It shows once a model is loaded, when it answers a real
question: did this model fit, and is the machine saturated. The GPU and VRAM
readouts appear only on a machine that has them (Windows with an NVIDIA
driver), and the absence on macOS is the platform difference made visible, not
an unfinished part.

## Do's and Don'ts

### Do

- **Do** take every colour, radius, spacing step and font size from the kit's
  tokens. A literal hex or pixel value in a component is a bug, even when it
  is the right one: it is a second place to change it.
- **Do** give every focusable control a visible focus state, and check it by
  pressing Tab rather than by reading the stylesheet. This app is driven from
  the keyboard; a control without a focus ring is a hole in the main path.
- **Do** give a pressed control a physical cue, not a dimmed one. Never scale
  a control on press.
- **Do** hand focus to a chosen neighbour before hiding or disabling the
  element that holds it, so the browser does not pick one and scroll to it.
- **Do** state a state on the surface where the user is already looking: the
  status strip for the model and the processor, the sidebar for recording, the
  status line for transcribing, the capsule for what happened to the words.
- **Do** let the operating system's reduced-motion preference decide how far
  something travels, and keep the fade. Reduced motion means gentler, not
  absent: a confirmation that arrives without a visible arrival is one the
  user can miss.
- **Do** capture both platforms. A Windows capture shows GPU and VRAM in the
  status strip when the machine has them; a macOS capture shows CPU and RAM
  only. Neither is the wrong one.
- **Do** keep an icon's colour a token. A colour baked into an SVG is
  permanently one palette behind.

### Don't

- **Don't** reach for emoji. They render unevenly across platforms and are
  unreadable in the monospaced Logs view. Use the kit's icons.
- **Don't** add gradients, glass or `backdrop-filter`.
- **Don't** add a second shadow value. Give the new surface a border and a
  lighter fill first.
- **Don't** add another type size or a second font family. If a size is too
  small or too large, the fix is weight, or the text-scale control, which
  exists so that a legibility need never becomes a new token.
- **Don't** hard-code a font size in px: it silently escapes the text scale.
- **Don't** take a control out of the tab order to stop a focus jump. Fix the
  jump. A mouse-only control in a keyboard-first app is a regression.
- **Don't** invent a light theme by inverting a dark one. The state colours
  are calibrated against their ground, and an inversion lands them somewhere
  else entirely.
- **Don't** let muted text ride a raised surface unchecked. Muted ink clears
  its contrast floor on the ground only; verify before reusing it on a chip or
  a panel.
- **Don't** animate a state that text already carries. If a label says
  "Recording", a pulsing dot beside it adds animation debt and no meaning.
- **Don't** put primary ink on a saturated fill without measuring the
  contrast. A fix is the pairing rule (ink on fill), never a new token.
- **Don't** put a level colour on a card-level surface in Logs. If a line
  needs a colour the ground cannot carry, the surface is wrong, not the colour.
- **Don't** keep a colour for a component that no longer exists. A reserved
  colour is a claim about the future that nobody is keeping.
- **Don't** treat a high share of a frame budget as a performance problem
  without reading the wall clock. Measure the user's experience, then the
  ratio.
