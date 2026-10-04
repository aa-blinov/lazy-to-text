---
name: Lazy to Text
description: Press a hotkey, speak, paste — a local-first dictation console.
colors:
  bg-primary: "#1d2021"
  bg-secondary: "#282828"
  bg-elevated: "#32302f"
  bg-hover: "#3c3836"
  accent: "#83a598"
  accent-hover: "#a89984"
  accent-focus: "#d5c4a1"
  text-primary: "#fbf1c7"
  text-secondary: "#bdae93"
  text-muted: "#928374"
  border: "#504945"
  success: "#b8bb26"
  danger: "#fb4934"
  warning: "#d79921"
  warning-hover: "#fabd2f"
typography:
  display:
    fontFamily: '"Inter Variable", "Inter", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "22px"
    fontWeight: 600
  headline:
    fontFamily: '"Inter Variable", "Inter", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "17px"
    fontWeight: 600
  body:
    fontFamily: '"Inter Variable", "Inter", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "13px"
    fontWeight: 400
  label:
    fontFamily: '"Inter Variable", "Inter", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.5px"
  reading:
    fontFamily: '"Inter Variable", "Inter", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "14px"
    fontWeight: 400
rounded:
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-default:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "9px 18px"
  button-default-hover:
    backgroundColor: "{colors.bg-hover}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "9px 18px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "9px 18px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "9px 18px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.danger}"
    rounded: "{rounded.sm}"
    padding: "9px 18px"
  button-danger-hover:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "9px 18px"
  button-filter-chip:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "4px 12px"
    typography: "{typography.label}"
  button-filter-chip-checked:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "4px 12px"
    typography: "{typography.label}"
  card:
    backgroundColor: "{colors.bg-secondary}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
  card-active:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
  input:
    backgroundColor: "{colors.bg-secondary}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
  input-mirrored:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
  input-invalid:
    backgroundColor: "{colors.bg-secondary}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
  checkbox:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-primary}"
    rounded: "4px"
    width: "16px"
    height: "16px"
  nav-item:
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "10px 14px"
  nav-item-hover:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "10px 14px"
  nav-item-selected:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "10px 14px"
  spec-line:
    backgroundColor: "transparent"
    textColor: "{colors.text-muted}"
    typography: "{typography.label}"
  pill-model:
    backgroundColor: "{colors.success}"
    textColor: "{colors.bg-primary}"
    rounded: "{rounded.sm}"
    padding: "4px 12px"
    typography: "{typography.label}"
  pill-recording:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "3px 12px"
    typography: "{typography.label}"
  pill-recording-active:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "3px 12px"
    typography: "{typography.label}"
  pill-processing:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "3px 12px"
    typography: "{typography.label}"
  status-chip:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
  toast:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
  warning-banner:
    backgroundColor: "rgba(245, 158, 11, 0.086)"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
  dropzone:
    backgroundColor: "{colors.bg-secondary}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.lg}"
  dropzone-active:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
  overlay-surface:
    backgroundColor: "{colors.bg-elevated}"
    textColor: "{colors.text-primary}"
    rounded: "24px"
  recording-dot:
    backgroundColor: "{colors.danger}"
    rounded: "7px"
    width: "14px"
    height: "14px"
  scrollbar-handle:
    backgroundColor: "{colors.bg-hover}"
    rounded: "4px"
    width: "12px"
    height: "12px"
  table:
    backgroundColor: "{colors.bg-secondary}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
---

# Design System: Lazy to Text

## Overview

**Creative North Star: "The Night Desk"**

This is a dictation tool, and dictation happens at two in the morning with the
room dark and one window of somebody else's document in focus. The interface is
built for that desk. It never brightens, never decorates, and never asks for
attention it has not earned. A warm near-black ground lets the text the user is
dictating be the brightest thing on screen; the recording state and the loaded
model are the only things allowed to speak up.

The material is a desk, not a control room: flat fills, a four-step surface
ladder, and 1px hairlines that separate one plane from the next. Nothing
floats, nothing glows, nothing is translucent. Controls are built to be pressed
— a real 9×18px target, a physical displacement under the pointer rather than a
faded one — because a dictation app is operated by muscle memory on a global
hotkey, and the hand should be able to trust what it hits. Where a state has to be unmissable, the
system spends a chromatic token on it rather than an effect.

Colour is rationed to one voice. Sage is the only accent in the app, and it means
exactly one thing at a time: focus, selection, or the primary action. The
one further hue joins it: `success`, on a loaded model's pill and on the single
word "fast" in a model card's spec line. Both answer the same question — "is this
the one I want?" — and nothing else. There is no other chroma in the app. The system contains no gradients, no glass, no blur, and no emoji; the
confirmed anti-references are flatness and restraint, and the incumbent has never
violated either.

**Key Characteristics:**

- **Gruvbox ground** — a four-step surface ladder taken from the palette's own dark
  ramp (`dark0_hard` → `dark0` → `dark0_soft` → `dark1`), warm rather than
  blue-black. Measured neighbour steps of 1.11 / 1.12 / 1.13:1.
- **One accent** — Sage (`bright_blue`), spent on focus, selection, and the primary
  action; never decorative. Its hover and focus steps are separate tokens because
  Gruvbox ramps per hue rather than per lightness.
- **Hairlines, not shadows** — 1px borders carry all structure; exactly one
  drop shadow exists in the app, on the model card.
- **Four type sizes, no more** — 22 / 17 / 13 / 11px, one variable family.
- **Tactile controls** — solid targets, a physical press cue rather than a
  dimmed one, borders that brighten to the accent on hover.
- **Motion matches the display** — animation step count is derived from the
  monitor's refresh rate, clamped to 60–240Hz.

## Colors

The palette is **Gruvbox**, taken as published: the four-step surface ladder is the
palette's own dark ramp, the text is its light ramp, and the state colours are its
`bright_*` and `neutral_*` rows. Nothing here was invented to fill a gap, with one
recorded exception below. A sage accent carries meaning; three state colours carry
state; family colours exist only to identify a model at a glance.

Two properties of the palette drove more of these decisions than the hues did. It
is **warm** where the previous palette was cool, so the ground is brown-black rather
than blue-black. And it is **ramped per hue** — `faded` → `neutral` → `bright` —
rather than per lightness, so there is no single global "one step lighter" and
several tokens below exist only because of that.

### Primary

- **Sage** (`#83a598`, Gruvbox `bright_blue`): the only accent in the system. It
  marks focus (input and combo borders), selection (active sidebar item, selected
  table row, checked checkbox, checked filter chip), the primary button fill, the
  scrollbar and drag handle, and the processing state. It is never used as a large
  surface, never as a page background, and never as text on `bg_secondary` — it
  measures 5.48:1 there and clears text contrast.

  The palette's other blue, `neutral_blue` `#458588`, was measured and rejected as
  the accent: it is the more obviously "designed" choice, and it fails Ink-on-Fill
  both ways — 3.88:1 under the ground ink and 3.73:1 under Ink Primary, neither
  above 4.5:1. `bright_blue` is the only blue in Gruvbox that carries a label.
- **Sage Hover** (`#a89984`, `gray_244`): the pointer-hover step for the accent.
  This is the one place the system uses a value that is not a `bright_*` or
  `neutral_*` row, and the reason is measured. Gruvbox has no second step inside a
  single hue — `bright_blue` is already the top of its ramp — and every lighter
  value the palette owns is warm, so "the accent, one step up" is not a colour that
  exists. The louder candidates were rendered on a filled primary button and
  rejected: `light2` does not read as a brighter button, it reads as a different
  button. `gray_244` measures 5.90:1 under the ground ink and sits at 1.03× the
  accent's luminance, so a sage button becomes a slightly warmer sage and nothing
  else.
- **Sage Focus** (`#d5c4a1`, `light2`): the keyboard-focus step, and the one place
  the accent is allowed to leave its hue. A pointer hover and a keyboard focus want
  opposite things from the same job — hover is a nudge, focus is a statement about
  where the arrow keys are — and a 3% luminance step does not say the second thing.
  `light2` is the strongest value in the palette that still carries the ground ink
  at 9.56:1. Used for the focused sidebar row and as the sheen on the Dock icon.

### Secondary

Gruvbox's `bright_*` row is already calibrated to be read as light text on a dark
ground, so the state colours come straight off it and no state colour looks louder
than another.

- **Moss** (`#b8bb26`, `bright_green`): success and "ready" — the active-model pill,
  the toast title, the done state of the transcribe status, and the passed result of
  a hotkey test. It is an olive rather than a grass green, which is what makes it
  sit quietly beside Sage instead of competing with it.
- **Ember** (`#fb4934`, `bright_red`): destructive and recording — the recording
  pill, the recording dot in the overlay, the outlined danger button, the
  Cancel-load button, an invalid hotkey field, the ERROR and CRITICAL levels in the
  Logs view, and a failed test result. Because red already means "recording", it is
  never reused for a non-recording warning. It is the brightest red the palette has
  and still tops out at 4.77:1 on the ground — see the Log Console rule below for
  what that costs.
- **Amber** (`#d79921`, `neutral_yellow`): the in-between state — model loading, the
  processing dot, the mic-test warning, the WARNING level in the Logs view, and the
  tinted permission banner. Amber is used at roughly 10% opacity for a background
  and full strength for the 1px border, so a permission banner reads as a note
  rather than an alarm.
- **Amber Bright** (`#fabd2f`, `bright_yellow`): the hover step for Amber, one step
  lighter in the same hue — the warning banner's button is a filled amber chip and
  its hover has to be visible against it.

### Tertiary

_Empty, and it stays empty._ An earlier system reserved an "Engine Green" for a
filled engine pill that was never wired up: the ENGINE line in the sidebar's status
chip is a `chip-value` **text** chip that reports the live ONNX Runtime provider in
`accent` or `text_secondary`, exactly like STATUS. The green stayed in the palette
for years after the component that used it was gone, and the new palette has no
room for it. It is recorded here as removed rather than quietly deleted, because
the next person to want an engine pill will look for its colour and should learn
that the question was already answered: the chip is text, and its state colour is
the accent.

### Neutral

Gruvbox names these steps, and the names are used here so that a hex quoted from
anywhere in the project can be traced back to a row in a published palette.

- **Ground** (`#1d2021`, `dark0_hard`): the window background, and the ink colour
  used on top of any state-coloured fill. It is the app's true black, warm rather
  than blue.
- **Card** (`#282828`, `dark0`): the second surface — cards, inputs, the sidebar,
  the topbar, table bodies.
- **Raised** (`#32302f`, `dark0_soft`): the raised surface — buttons, badges, chips,
  the toast, the overlay, the recording-status chip, alternate table rows.
- **Hover** (`#3c3836`, `dark1`): hover only. It appears on button hover and as the
  resting scrollbar handle, and is the top of the ladder.
- **Ink Primary** (`#fbf1c7`, `light0`): headings, body copy, and focus rings. Not
  pure white — the cream is what keeps it from vibrating on a warm dark ground.
- **Ink Secondary** (`#bdae93`, `light3`): descriptions, hints, muted metadata,
  resting nav items, the log console's default text.
- **Ink Muted** (`#928374`, `gray_245`): captions, placeholder text, disabled text,
  format lists, log timestamps, the disabled input's mirror state.
- **Hairline** (`#504945`, `dark2`): every border in the app. It is the same hue as
  the surface it sits on, lifted one step.

### Named Rules

**The One Accent Rule.** Sage is the only chromatic voice in the app chrome, and it
carries exactly one meaning per surface: focus, selection, or primary action. If a
new element reaches for the accent, one of those three is its job; if none of them
is, the element is not accent-coloured.

**The Ladder Rule.** There are four surfaces and no fifth. A new surface either
reuses one of the four or the ladder grows deliberately, as a change to
`theme.py` — never as a one-off hex inside a widget. Measured neighbour steps are
1.11:1, 1.12:1 and 1.13:1: even, which is what a ladder is for. A steeper ramp
looked more "designed" and cost the ability to see where one plane ended and the
next began.

**The Ink-on-Fill Rule.** A label sitting on a *saturated* fill — accent, danger or
warning — is the Ground, never Ink Primary. Measured: Ink Primary on the Sage fill
is 2.37:1, on its hover 1.51:1, on danger 3.03:1 and on warning 2.19:1 — every one
of them far under the 4.5:1 AA floor. Ground on the same fills is 6.09:1, 5.90:1,
4.77:1 and 6.61:1, and 9.56:1 on Sage Focus. The loading pill and the
warning-banner button already followed the rule, so the rest were drift rather than
intent and now match their own neighbours.

**Focus rings are the deliberate opposite and stay Ink Primary.** A ring's outer
edge meets the window ground, where Ink Primary measures 14.45:1; its inner edge
meets the accent fill, where Ink Primary is weak. The label beside the ring going
dark changes nothing about that reasoning. Do not "fix" a ring to match its label.

**The Verb Does Not Outgrow The Sentence Rule.** A permission banner is one
paragraph plus the verb that fixes it, and the verb never gets more room than
the paragraph. Measured before this rule existed: at text scale 1.75 in a 900px
window the microphone banner gave its button **53%** of the row, wrapped the
message into eight lines, and stood 246px tall for a single sentence.

Three things hold it, and the first two are copy. The paragraph names the System
Settings pane, so the button does not repeat it — the labels are `Grant access`
and `Open Settings`, verbs rather than sentences, and the pane path belongs to
the prose beside it. Then `_PermissionBanner` caps the button at half the row in
`resizeEvent`, because a `QHBoxLayout` hands leftover space to the stretch item
but nothing stops a wide `sizeHint` from winning the row outright, and this
button's hint grows faster than the label's minimum shrinks. The cap is a
backstop, not the mechanism: with the shipped labels the button stays well inside
its share, and a test asserts the cap never actually binds, because a cap that
elides its own label would trade one clipping bug for another. The result is
**162px and five lines** at the same size and scale.

**The Reading Surface Is A Well Rule.** The two panes whose whole job is to be read
— the Logs console and the Transcribe transcript — sit on the ground, not on a card.
They are sunk into it and kept in shape by their hairline. This is not a styling
preference: it is the only place `bright_red` clears AA as text. On `bg_secondary`
it measures 4.29:1 and on `bg_elevated` 3.82:1, and no red in the palette is lighter,
so a coloured error line and a card-level surface are mutually exclusive here. The
surface moved, not the colour. It also happens to be right: light-on-dark reads
hardest on the deepest plane, and the text the user came for should be the brightest
thing on screen.

**The Icon Is An Ink Rule.** An icon takes its colour from the surface it sits on,
and a bundled SVG is a template, never a picture: its stroke is a `{{color.*}}`
placeholder resolved at raster time, so no hex ever lives in `styles/icons/`. The
sidebar's five icons are drawn in three inks — `text_secondary` at rest,
`text_primary` under the pointer, and the **ground** on the selected row. That last
one is the Ink-on-Fill rule applied to a glyph, and it is not a detail: the
selected row's fill is the accent, or `accent_focus` under keyboard focus, and Ink
Primary on those is 2.37:1 and 1.51:1. The icons used to be baked at the previous
palette's near-white and nothing could reach them — QSS `color` never paints a
`QIcon`'s pixels, and the `::item` colour rules that darkened a selected *label*
left its *icon* white on a cream pill. Qt documents `QIcon::Active` as the mode for
a hovered item and this list never reaches it (measured against a three-colour icon
under a real `QTest.mouseMove`: hovered rows rendered `Normal`, selected rows
`Selected`, and `Active` never appeared), so the sidebar applies the hover tint
itself. The tray and Dock icons are the one documented exception — they are macOS
template images, pure black on transparent with `setIsMask(True)`, and the OS tints
them per appearance.

**Measured contrast (WCAG 2.1 ratios, computed from these values).** Ink Primary on
Ground is 14.45:1 and Ink Secondary is 7.53:1 — both comfortable. Ink Muted is the
one remaining place below the 4.5:1 text threshold and is treated as known debt, not
as precedent: 4.47:1 on Ground, 4.02:1 on Card, 3.58:1 on Raised and 3.16:1 on the
hover step, so muted text only clears the bar on the base surface. Sage Hover is
5.90:1 on Ground and 5.30:1 on Card, so it is usable as an ink but is not used on
Raised. Status hues as text on Card: Moss 7.14:1, Amber 5.94:1, Sage 5.48:1, Ember
4.29:1 — which is the same fact the Reading Surface rule exists to solve.
PRODUCT.md records that no accessibility standard has been chosen for this product
yet; these numbers are the reason that decision matters.

## Typography

**Display Font:** Inter Variable (bundled `InterVariable.ttf`, with Inter,
Segoe UI Variable, Segoe UI, Helvetica Neue, Arial, sans-serif as the fallback
stack)
**Body Font:** the same single family
**Label/Mono Font:** none — the Logs view uses the same family for its
colour-coded lines

**Character:** Inter is a working interface face — tall x-height, open
apparforms, and unambiguous 1/l/I at 11px, which matters when a chip label is
the only thing distinguishing `fp16` from `fpl6`. The variable cut ships with
the app so the machine never has to have Inter installed. There is no display
face and no serif: the personality lives in weight and colour, not in
typographic contrast.

### Hierarchy

- **Display** (600, 22px): one role only — the page-level title. Rare enough
  that a view may not use it at all.
- **Headline** (600, 17px): section headings, model names on a card, and the
  empty-state title. This is the size a user's eye lands on first.
- **Body** (400, 13px): the working size — descriptions, status lines, table
  content, button labels (at weight 500 in buttons). Long transcription output
  should be held to roughly 75 characters per line; the transcribe output
  area is the one place it runs longer.
- **Label** (600, 11px, 0.5px tracking): captions, chip values, section
  headers, badges, and every pill. At this size weight carries the meaning:
  700 for overlay titles, 600 for labels and values, 500 for
  inline test results. Section headers add 1px tracking and `text-transform:
  uppercase`.
- **Reading** (400, 14px): the transcribe output only. The single place the
  user reads somebody else's long text, so it is the one size above Body.
  It was two hard-coded `14px` rules before, which meant it also escaped the
  text scale; it is a token now, like every other size.

**Text scale.** Every `font.size_*` token is multiplied by one user-facing
factor (100% / 115% / 130% / 150% / 175%, set in Settings → Appearance, stored
as `ui.text_scale`). At 100% the stylesheet is byte-identical to the unscaled
one. Radii and spacing are deliberately *not* scaled: a larger text size
should grow the reading surface, not break the four-step layout rhythm, and
the card radii are what make the app read as one object. Scale is applied at
token-substitution time in `theme.py`, never as a per-rule override, so it is
impossible for one rule to be left behind.

### Named Rules

**The Four Sizes Rule.** The system has exactly four sizes: 22, 17, 13, and
11px. A fifth size is drift, not a scale. The transcribe view's hard-coded 14px
is pre-existing drift and is not precedent.

**The Weight-at-11px Rule.** Below 12px, weight does the work that size
normally does. 700 for identity (which model family), 600 for state (what is
happening), 500 for quiet emphasis. Never use colour alone to carry a label's
meaning at this size.

## Layout

The shell is a fixed spine. A 200px sidebar runs the full height on the left
and a 52px topbar crosses the top; the topbar reserves a transparent gutter
exactly as wide as the sidebar so its real content aligns to the sidebar's
right edge, which is what makes the two read as one object rather than two
panels stuck together. Neither dimension is ever computed — both are
constants duplicated deliberately in `sidebar.py` and `topbar.py` — because a
spine that flexes with window width would stop the alignment.

Content sits inside a fixed frame on every view: 28px horizontal margins, 22px
vertical, 14px between a view's sections, 16px between cards. The window opens
at 1100×780 with a 900×620 floor; below that floor the layout does not reflow,
it scrolls, because the model card is the densest object in the app and its
description and spec line wrap rather than compress.

The floor is measured, not inherited. With it removed at runtime and each view
checked for horizontal overflow in its own live scroll area: at text scale 1.0,
700×560 is clean on all five views and 650×532 is clean on four (Settings
overflows 42px); at 1.75, 900×620 is clean on all five and 760×600 puts a
15px scrollbar on Settings. Qt's own `minimumSizeHint` for the same layout is
650×532, which does not see content minimums at all. So 900×620 is the size at
which the *worst* supported text scale stops overflowing, and a 1366×768 laptop
at Windows 150% scaling lands right there.

The Models view is a single full-width column, not a grid. Cards are wide
enough to hold a title, a one-line description, and a full row of metadata
spec line without wrapping, and a narrow grid would turn every card into five
lines of stacked fragments. The card stack carries 4px of inner padding on all sides —
not for breathing room, but so the card's drop shadow has somewhere to fall
instead of being clipped by the scroll area. Empty states are centred in a
40/60px frame with an 8px gap between title and hint.

**The Own-Width Rule.** A control group changes its structure from the space
it actually has, never from a device or window-size list. The inference
settings panel is the case in point: Language, Beam size and Temperature sit
in a two-column grid by default, and collapse to a single column when the
available width falls under what that grid needs — 450px at the default type
scale, 696px at 175%. The floor is computed from the widgets' own `sizeHint`,
so it follows the type scale instead of assuming one. The collapse costs
vertical space, which this panel can spare: it lives at the bottom of a card
inside a vertical scroll area, where a horizontal scrollbar would cost the user
the whole card.

**The Fixed Spine Rule.** 200px and 52px are constants, and the topbar gutter
must always equal the sidebar width. Alignment of those two planes is the
app's only structural ornament; do not trade it for density.

**The 28/22 Frame Rule.** Every view's content frame is 28px horizontal and
22px vertical. A view that invents its own margins will not match its
neighbours, and the mismatch is visible at a glance because the sidebar gives
every view a hard left edge to align to. `TranscribeView` sat at 24/24 for
long enough to be worth naming here; the rule is now measured, not trusted —
`tests/gui/test_page_identity.py` walks to the page header in every view and
asserts its content lands on 28.

## Page Identity

**Every view names itself.** A 22px title and one line of purpose sit above
the view's controls, built once by `PageHeader` and used by all five. The
system had the vocabulary the whole time — a `size_title` token and a
`QLabel[role="title"]` rule — and no real view used either; only
`placeholder.py`, the screen the app never shows. The symptom was not ugly
buttons, it was that Transcribe, History, Logs and Models all read as one
long settings panel, because nothing on screen said which section you were in.

The purpose line is Ink Secondary, not Ink Muted: this is the line that
explains what the section is *for*, so it has to survive being read, and Ink
Muted is already the app's known contrast debt.

**One primary action per view, and it means something.** The accent is spent
on "focus, selection, or the primary action", so an accent-filled button
promises to be the thing to press. Transcribe offered Browse / Copy / Save
at identical weight; History put `Clear` — destructive, one click from the
search box — in the same grey as `Copy`. Now: Browse and Copy are primary,
`Clear` is `danger`, and a card list is exempt by design, because each card's
`Download`/`Select` is the primary action *of that card*.

**Destructive actions are marked.** Anything that discards — `Clear` in
History and Logs, the Hugging Face token reset in Settings — carries
`role="danger"`. The HF token button was found this way: a test asked which
buttons claim to destroy something and found one that had been shipping
painted like a neutral control.

## Empty States

An empty state is the screen's job before there is data, not a gap in the
layout. It carries three things: what is missing, why, and what to do — and
it stands on the same card the content will, because a bare region stops
reading as a surface and becomes a hole in the window. `EmptyState` is one
widget used by History, Logs and Transcribe, which previously had three
different answers to the same question and one of them (Logs) gave the user
nothing at all. Where the answer is a key press, the key is a monospaced cap
under the sentence rather than part of it — the most skimmable line on the
screen should not look like every other sentence.

Logs keys its empty state on the *buffer*, not on what survived the filters:
a search matching nothing shows an empty stream, not a claim that the app
has never logged anything.

**Instrument telemetry appears when it has something to say.** The topbar's
CPU/RAM meter was pinned visible on every screen, reading 0%, because a
gauge that cannot move occupies the best position on the window to say
nothing. It is now hidden until a model is loaded — at which point it
answers a real question: did this model fit, and is the machine saturated.

## Elevation & Depth

This system is **flat, with exactly one shadow**. Depth is carried by a
four-step tonal ladder and 1px hairlines: a surface one step lighter than its
parent reads as raised, and a 1px `border` colour one step lighter than the
surface it outlines reads as an edge. Qt's QSS has no `box-shadow`, so the
single shadow in the app is a `QGraphicsDropShadowEffect` on `ModelCard` —
blur 24, offset 0/4, black at 39% opacity — and it exists for a specific
reason: the model card is the only object in the app that behaves like a
selectable physical item, and the shadow is what makes it feel liftable before
the user has clicked anything.

### Shadow Vocabulary

- **card-float** (`blur 24, offset 0px 4px, rgba(0, 0, 0, 0.392)`): model cards
  only. Not for panels, not for the toast, not for the recording overlay — the
  overlay is a floating window, so it earns depth from the window manager, not
  from a painted shadow.

### Named Rules

**The Hairline Rule.** Draw structure with 1px borders. Reach for a shadow only
when the object is genuinely a liftable item in a list; a container that merely
*contains* things gets a border and one step of background.

**The One Shadow Rule.** There is one shadow value in this system. A second
surface that wants depth gets a border and a lighter fill instead. If a real
second use for a shadow appears, it is a change to this file, not a local
decision.

### Forced Colours

Windows high-contrast mode exists because the user has hand-picked a palette
they can read — for low vision, for sunlight, or for a screen they simply
trust more than ours. Painting our own ground over it defeats the entire point, so in
that mode the app drops the stylesheet entirely (`load_stylesheet` returns an
empty string) and hands the window back to the OS palette, letting Qt's own
forced-colour handling take over. The mode is detected through
`SystemParametersInfoW(SPI_GETHIGHCONTRAST)`, because Qt 6.11's
`QStyleHints.colorScheme` reports only `Dark` / `Light` / `Unknown` and never
flags forced colours. A 1s poll re-checks it, so flipping the OS switch repaints
the app without a restart. macOS has no equivalent mode and is unaffected.

**The Spec Is Not A Pill Rule.** A pill is a state or a tag; a specification is
text, and putting one inside the other is a category error a reader pays for
in scanning cost. Rounded boxes destroy horizontal rhythm and alignment, so a
row of them cannot be compared down a column the way a line of numbers can.
Measured: the model card went from seven pills to one line, and the view from
63 pills to 0. The corollary is that a specification earns colour only for a
*verdict*, never for a fact — `1.6 GB` stays muted, `fast` gets `success`,
because "this one is quick" is an opinion and "1.6 GB" is a number.

**The Defer Rule.** When the OS is in a forced-colours mode, the OS palette
wins — all of it, not just the parts that clash. A partial override would leave
the user with a hybrid neither they nor the designer chose.

## Shapes

Radii are plump and consistent, and they encode what kind of thing you are
touching. **8px** for anything you press or that is small and dense — buttons,
inputs, badges, chips, pills, nav items, the checkbox, the status chip, the
warning banner. **12px** for panels and transient surfaces: the toast, the
inference-settings sub-panel, the transcribe output area, the inline warning
label. **16px** for cards and drop zones. **20px** is reserved and currently
unused in shipped UI.

Two shapes deliberately break the scale. The **recording overlay** uses 24px
because it is a floating object hanging over another application, not a panel
inside ours — it should read as a different kind of object at a glance from
across the screen. The **recording dot** uses 7px on a 14px circle, which is
fully round; a rounded rect there would read as a bug, not a state. The
**scrollbar handle** uses 4px on a 12px track, a capsule that stays out of the
way of content.

Icons are 24px stroked SVGs at 1.6 stroke width, round caps and joins, bundled
under `app/gui/styles/icons/` — the sidebar set (models, transcribe, history,
logs, settings) plus microphone, chevron-down, arrow-path, and the checkbox
tick. They are the only iconography the app has.

None of them carries a colour. Every stroke that needs one is a
`{{color.*}}` placeholder, and `theme.py` resolves it at the moment of use:
`icon_pixmap` for anything Qt draws itself, `resolve_icon_svg` for rich text
that needs the SVG inlined, and `resolved_icon_file` for the combo's chevron,
which is the one icon QSS paints and `image: url(...)` accepts nothing but a
path. Each takes a **token name**, never a hex — passing one raises. The tray
and Dock icons read `currentColor` and are rendered as macOS template images
the OS tints; that is the intended reading of the attribute, not a
placeholder someone left behind. See The Icon Is An Ink Rule.

**The Radius Means Density Rule.** 8px is dense and pressable, 16px is a card
you read. A control that grows past 16px radius has stopped being a control.

## Components

### Buttons

Tactile and confident. Every button is a real target with 9px vertical and 18px
horizontal padding and a minimum content height of 16px, so the pressable area
is the painted area — there is no invisible padding around a small label.

- **Shape:** gently rounded (8px radius), 1px border.
- **Default:** raised fill (`bg_elevated`) on 1px Hairline, Ink Primary text at
  weight 500. Hover lifts the fill to `bg_hover` and turns the border to
  `accent_hover`; press drops the fill to `bg_secondary`.
- **Primary:** solid Sage fill with a matching border, weight 600, and the ground
  colour as its label. Hover to Sage Hover. This is the only filled-accent button
  in the system.
- **Danger:** transparent fill with a 1px Ember border and Ember text at rest,
  filling red on hover. Outlined so it stays visibly subordinate to the primary
  action sitting beside it (Delete beside Select, Cancel beside Download).
- **Disabled:** `bg_secondary` fill, Hairline border, Ink Muted text — visibly
  inert without changing the button's shape or position.
- **Focus:** a 2px ring, drawn inward (padding drops 1px per axis so the
  button never resizes under the user's finger). The ring is Sage on every variant
  except the two that are already accent-filled — the primary button and a checked
  filter chip — where an accent ring would be invisible and the ring becomes Ink
  Primary instead. Danger keeps Ember: red is that control's identity, and
  switching it to the accent would read as a different action.

### Chips And Specs

A pill is a state or a tag. A specification is text. They are not
interchangeable, and the model card is where the line sits.

- **Filter chips** (`All / Whisper / GigaAM / …`) are buttons: `bg_elevated`
  fill, Hairline border, Ink Secondary text, 4×12px padding at 11px. Checked
  state fills Sage with the ground colour as its text.
- **State pills** — the card's `Active`, the topbar's current model — are
  filled `success` with the ground colour as their text. They are the same
  fact in two places, so they are the same colour; the topbar chip used to be
  tinted with the *whisper* family hue regardless of which model was loaded,
  which was arbitrary, since a family colour has no opinion about Parakeet.
- **The model card's spec line** is not a pill and never was, eventually. It
  reads `1.6 GB download · 4.0 GB VRAM · fast`, in Ink Muted at label size,
  with only `fast` in `success`. It was seven pills, then four, then this.

The seven were a family chip plus six metadata pills: 63 across the view, 7
per card. Each was removed against the nine shipped models, not by taste —
see *Model Cards* below. A badge that repeats the thing it labels, or that
reads the same on eight of nine cards, is furniture.

### Cards / Containers

- **Corner Style:** 16px radius.
- **Background:** `bg_secondary` at rest, `bg_elevated` when active.
- **Border:** 1px Hairline, brightening to `accent_hover` on hover and to `accent`
  when the card is the active model.
- **Shadow:** `card-float`, the app's only shadow.
- **Internal Padding:** handled by the view's 28/22 frame; the card itself
  relies on its own layout, with a 1px top border and 8px top padding
  separating an expanded inference-settings panel from the card body.
- **Focus:** the card is its own tab stop, because it is where focus lands
  when the Download button hides itself as the card turns Active. An
  inactive focused card gets a 2px accent ring; the active one gets Ink
  Primary, since its accent border already means "this is the loaded
  model".

### Inputs / Fields

- **Style:** `bg_secondary` fill, 1px Hairline, 8px radius, 6×10px padding, 13px
  text. Combo boxes replace the native drop-down with a bundled chevron SVG
  because Qt's default sub-control draws a square chip that breaks the radius.
- **Focus:** the border shifts to Sage. No glow, no second border.
- **Invalid:** the border shifts to Ember and *stays* Ember on focus — a focus
  state must not overwrite an error state. The human-readable reason belongs in
  the tooltip.
- **Mirrored** (`[muted="true"]`, a field tracking another value): `bg_elevated`
  fill with Ink Muted text. This reads as "not editable right now" without
  disappearing the way a disabled widget does.
- **Checkbox:** a 16px square at 4px radius, `bg_elevated` fill, Hairline
  border; checked fills Sage and draws the bundled tick in the ground colour.

### Navigation

The sidebar is a five-item list — Models, Transcribe, History, Logs, Settings —
each a 24px stroked icon plus a 13px label, padded 10×14px with an 8px side
margin and 2px vertical separation, at 8px radius. Resting items are Ink
Secondary on transparent; hover lifts to `bg_elevated` with Ink Primary; the
selected item fills Sage with the ground colour as its text and carries the only
accent-coloured plane in the chrome. There is no hover-only affordance and no
icon-only collapse — the list is always five labels, because the app is navigated
by keyboard shortcut (`Ctrl+1..5`) as much as by pointer.

The whole sidebar is **one** tab stop, not five: the list takes focus and arrow
keys move between items. Because focus lands on the widget and never on a row, the
focused state has to be expressed in the fill: **the selected row lifts from Sage
to Sage Focus while the list holds keyboard focus**, and returns when focus leaves.
It is Sage Focus and not the same token the pointer hover uses because those are
different jobs — a pointer nudge of 3% luminance would be invisible here, and a
paper-bright fill under a moving mouse would be alarming. The accent is already
spent on meaning "focus, selection, or the primary action" — a nav row that is
selected *and* keyboard-driven is the first of those.

Two shapes were measured and rejected before this one. A
`#SidebarList:focus` border frames the *widget*, which is a 200 × 601 px
column running down the empty space under the last item — a stray border,
not an indicator. A delegate that strokes the row is worse: Qt hands a
delegate the unmargined item rect (192 px) while the stylesheet paints the
pill inset by its own margin (12..187), so the stroke lands ~11 px off the
fill on one side and flush on the other. Neither adds anything a fill lift
does not, and both put a mark on a surface the design system wants quiet.
The lift is applied as a widget-level stylesheet, so the repolish stays
inside the sidebar and the pill keeps the radius, padding, and position the
stylesheet gave it.

Every action in Settings and on a model card is individually Tab-reachable —
nothing in the app is mouse-only.
### Pills

Pills are the app's status channel, and they are small: 11px at weight 600,
4×12px padding, 8px radius, in the topbar and the sidebar's status chip.

- **Model pill** — the loaded model, in the family's ink; empty state drops to
  `bg_elevated` on Ink Muted; loading fills Amber.
- **Engine pill** — the live ONNX provider in the accent; drops to `bg_elevated`
  on Ink Secondary when the accelerator is unavailable and inference has fallen
  back to CPU. This is deliberate, not an error.
- **Recording pill** — `bg_elevated` at rest; Ember filling while recording, Sage
  while processing, Amber while a model loads.
- **Status chip** (sidebar, bottom-left) — mirrors the topbar at card geometry,
  with a live VU bar beneath the value so a muted or dead microphone is visible
  *before* the user finishes speaking.

**The Pill Is State, The Chip Is Identity Rule.** Pills report live process
state and may change colour at any moment. Chips report fixed model identity
and never change. If a pill starts behaving like a chip, or a chip starts
animating, the two channels have merged and the topbar stops being readable at
a glance.

### Signature Components

**The Recording Overlay** is a frameless, always-on-top, transparent window
that appears over whatever the user is dictating into, including fullscreen
apps. It carries a 24px `bg_elevated` surface, a fully round status dot (Ember
while recording, Amber while processing), a weight-700 title, and a
body line in Ink Secondary. It is the one surface in the app that is not inside
the app, and it is designed to be read from across a desk in peripheral vision —
which is why its geometry deliberately leaves the radius scale.

**The Resource Blocks** (topbar) are drawn, not styled: each is a tiny label, a
right-aligned value, and a 5px capsule bar drawn with `drawRoundedRect` on a
`bg_secondary` track, rounded 2px. CPU and RAM always; GPU and VRAM on Windows
only, with the GPU block hiding gracefully on machines without NVIDIA. They update
every two seconds, and the whole widget is hidden until a model is loaded —
telemetry that reports "no model" is not telemetry, it is noise with a progress
bar. On macOS the GPU block's absence is the platform difference made visible, not
a missing feature.

**The Model Card** is the app's densest object and the reference for how
information density is handled here: model name, repository id with an
external-link affordance, one-sentence description, a spec line, and the
action button right-aligned on its own line so the button never competes
with the text. A card is a selectable item first and a container second.

**Seven pills, then four, then none.** The card used to carry a family chip
and six metadata pills — 63 across the view. Every one was removed against the
nine shipped models, never by taste:

| Removed | Why |
| --- | --- |
| family chip | repeated the title in 9/9 — "WHISPER TURBO" beside "Whisper Large v3 Turbo". Grouping is the filter row's job. |
| `lang` | repeated the model name — "Parakeet TDT v3 (multilingual)" |
| `compute` | float16 on 8/9; the Parakeet float32 exception is a backend detail the inference panel owns |
| `quality` | "excellent" on 8/9, and "Quality dips on accented speech" says more than the word "good" |
| `size` → text | survives, but as text: 30 MB to 3.1 GB, a 100× spread |
| `vram` → text | survives, but as text: 0.5–6.0 GB, a 12× spread, in no description |
| `speed` → text | "at 6× speed", "Fastest multilingual ASR", "ultra-lightweight" — six of nine descriptions say it better than the word "fast" |

The rule that fell out: **a pill is a state or a tag; a specification is
text.** Four rounded boxes per card was a table that had lost its alignment —
four key-value pairs, same shape, same weight, shouting metadata at a reader
scanning a column. The card now carries one quiet line and **zero pills**;
only the `Active` state pill remains, because that one really is a state. The
tallest card shrank 233px → 202px on the way, and 63 pills became 0.

**The Toast** is the product's payoff and the app's one authored motion. It
confirms that a dictation landed, which usually happens while the user is
looking at a *different* window — they pressed a hotkey blind, spoke, and
this banner is how the app answers. So it arrives with a temporal edge: 180ms
rising 12px out of the bottom-right corner it already rests in, fading from 0
to 1 on `OutQuart`, and it leaves in 120ms on `InQuad` — faster out than in,
because a departing banner is not arriving anywhere. A second message at a
visible toast updates the text and re-arms the timer but does not replay the
arrival; two transcriptions in a row are one continuous confirmation, not two
events. `hide_message()` is the exception and stays synchronous: it is the
imperative verb, and a caller that gets control back expects no banner left
on screen to sit over whatever it opens next.

**Motion is a preference, not a setting.** Both operating systems ship a
switch for less movement — macOS Accessibility → Display → Reduce motion
(`NSWorkspace.accessibilityDisplayShouldReduceMotion()`), Windows Accessibility
→ Visual effects → Animation effects (`SPI_GETCLIENTAREAANIMATION`) — and
PySide6 6.11's `QStyleHints` reports neither, exactly as it fails to report
forced colours. `app/gui/motion.py` reads them the same guarded way
`theme.is_high_contrast` reads its own. Under it, the scroll tween is dropped
for a single step (the user still asked for 40px and must land 40px away;
what goes is the 400ms of travelling to get there), and the toast keeps its
fade but loses its rise. **The arrival carries meaning; the travel does
not.** That is the iOS rule and the Material rule arriving at the same place
from two directions.

## Do's and Don'ts

### Do:

- **Do** resolve every colour, radius, spacing step, and font size through
  `TOKENS` in `app/gui/theme.py` and reference it in QSS as `{{color.*}}` /
  `{{radius.*}}` / `{{space.*}}` / `{{font.*}}`. A literal hex inside a rule is
  a bug, even when it is the correct hex.
- **Do** pair a family colour as surface + ink + border, and keep the triple in
  `theme.py` if it is reused outside one chip. Derive the surface and border by
  mixing the hue into `dark0_hard` at the two fixed ratios (10% / 40%), not by
  eye — five hand-picked tints are five taste calls, and one ratio is a rule the
  next person can apply.
- **Do** size motion to the display: use `tick_interval_ms()` for anything
  animated, and pass `max_rate=60` for the VU meter, because the audio buffer it
  samples only updates every ~10ms and faster redraws duplicate frames.
- **Do** give a pressed control a physical cue, not a dimmed one: the standard
  buttons drop their fill one step, and the compact cancel-load button
  displaces by 1px of padding. Never scale a control on press.
- **Do** capture both platforms. A Windows capture shows GPU and VRAM in the
  topbar; a macOS capture shows CPU and RAM only. Neither is the wrong one.
- **Do** give every focusable control a visible focus state, and check it by
  pressing Tab rather than by reading the stylesheet. This app is driven from
  the keyboard; a control without a focus ring is a hole in the main path.
- **Do** hand focus to a chosen neighbour *before* hiding or disabling the
  widget that holds it (`app/gui/focus.py`). Qt's own fallback picks the next
  widget in the chain, and inside a scroll area it will scroll to it.
- **Do** route the external-link affordance through `styles/icons/` as an SVG.
  A Unicode arrow is not an icon and a screen reader announces it as a
  direction, not an action.
- **Do** state a state on the surface where the user is already looking: the
  topbar for the model and engine, the sidebar chip for recording, the status
  line for transcribing.
- **Do** decide a control group's structure from its own available width, and
  derive the threshold from the controls' `sizeHint`. A breakpoint table keyed
  to window sizes goes stale the moment the user raises the type scale.
- **Do** let the OS preference decide how far something travels, and keep the
  fade. Reduced motion means gentler, not absent: a confirmation that arrives
  without a visible arrival is a confirmation the user can miss.
- **Do** read the platform motion setting through one guarded helper, the way
  `is_high_contrast` does, and cache it. The wheel path asks per notch, and a
  call that crosses into Objective-C or user32 on every tick is a stall.
- **Do** resolve every colour through `TOKENS` — in QSS *and* in Python. A
  `QColor("#32302f")  # bg_elevated` is a second place to change a colour, and a
  colour Python cannot reach is a colour nothing outside that widget can reach
  either. Rich text is the one honest exception to QSS, and it still resolves
  through the token rather than writing the hex out.
- **Do** check whether a QSS role is still set by any widget before trusting it.
  A styled role nothing sets is a rule that costs a line to read and can never
  render; three of them (`engine-pill`, `recording-pill`, `warning`) survived
  after the components that used them were replaced.

### Don't:

- **Don't** reach for emoji. It is banned by the project's own rules: emoji do
  not render correctly in the dark theme and are unreadable in the monospaced
  Logs view. Use the bundled 24px stroke SVGs in `app/gui/styles/icons/`.
- **Don't** add gradients, glass, or `backdrop-filter`. The surfaces are flat
  fills separated by 1px hairlines; depth is a background step, never an
  effect.
- **Don't** add a second drop-shadow value. Give the new surface a border and a
  lighter fill first.
- **Don't** add a fifth UI type size or a second font family. If 11px is too
  small or 13px is too large, the fix is weight — or the text-scale control,
  which exists exactly so that a legibility need never becomes a new token.
- **Don't** hard-code a `font-size` in px. A literal px size silently escapes
  the text scale; every size comes from a `font.size_*` token.
- **Don't** take a control out of the tab order to stop a focus jump. Fix the
  jump — that is what `release_focus_before` is for. A mouse-only control in a
  keyboard-first app is a regression, not a workaround.
- **Don't** leave a `Qt.NoFocus` on an action. It silences a focus chase by
  removing the control from the chain, and in this codebase that had cost
  twelve actions their keyboard path.
- **Don't** invent a light theme by inverting these values. `dark.qss` is the
  only stylesheet the app has ever shipped, and a mechanical inversion would
  break the calibrated state colours (Amber on Ground measures 6.61:1 as a fill;
  inverted, it is ink on a light ground and lands in a different place entirely).
  It would also break the surface ladder, which is four steps of a *dark* ramp by
  construction.
- **Don't** start a fourth palette. `docs/style.css` carries a parallel token set
  with the same names and unrelated values — `--bg-primary: #161616` against the
  app's `#1d2021`, `--accent: #4a9eff` against `#83a598`, `--radius-sm: 6px`
  against `8px`. The Gruvbox move widened that gap rather than closing it.
  Converging the landing page on the app's tokens is the fix; adding another set
  is not. Whether the landing page is part of this product at all is still an open
  question in `PRODUCT.md`, and it is the one thing that decides whether this is
  a bug or a separate surface.
- **Don't** bake a colour into a bundled SVG. It looks complete in review and
  renders fine; it is just permanently one palette behind, and nothing in the
  token system can reach it. The stroke is a `{{color.*}}` placeholder and
  `theme.py` resolves it — the sidebar icons sat at the previous palette's
  near-white for the whole Gruvbox migration, which is what made the cream
  selection pill read as washed out at 1.51:1.
- **Don't** trust `QIcon::Active` to carry a hover tint. It is documented for
  a hovered item and this list never renders it. The sidebar's hover icon is
  applied by hand for exactly that reason, and `tests/gui/test_nav_icons.py`
  pins all three states.
- **Don't** let muted text ride the raised surfaces unchecked. Ink Muted clears
  4.5:1 only on Ground; on Card it is 4.02:1 and on Raised 3.58:1. Verify before
  reusing it on a chip or a panel.
- **Don't** animate a state that text already carries. The recording dot was
  the obvious candidate for a pulse, and it earned none: the overlay reads
  "Recording / Speak now" beside it and the tray tooltip repeats it, so
  removing the pulse would lose no meaning. Motion that duplicates a label
  is animation debt.
- **Don't** crossfade a view swap on the Models page. Nine model cards each
  carry a `QGraphicsDropShadowEffect`, so a 150ms crossfade renders both
  pages at once with every shadow live. Price the effect before spending it.
- **Don't** animate an explicit `hide_*()`. Only the timed departure earns a
  fade; an imperative call has a caller waiting on the other side of it.
- **Don't** remove the card shadows to save a frame. Measured, 1100×780,
  offscreen, 9 cards: the shadows cost 3.77 ms of a 4.83 ms scroll frame, and
  a sustained 8-notch flick burns 89.8 ms of CPU against 45.0 ms without them.
  That is real, and it is also 12.9% CPU against a wall-clock flick that is
  *identical* to 0.5 ms either way — the app is 87% idle while scrolling.
  A frame can use 78% of a budget it has plenty of. The only refresh rate
  where this stops being true is 240Hz, where the 4.17 ms budget is smaller
  than the frame; if a 240Hz user ever reports jank, this is the lever, and
  the measurement above is the reason to reach for it then rather than
  earlier.
- **Don't** batch the Logs append path. It looks like the obvious win —
  `_rerender` batches and its docstring claims 500ms → <50ms — but
  `setUpdatesEnabled` per *record* is the pathological case: 368 µs/record
  unbatched against 1890 µs batched, because re-enabling updates forces a
  full document re-layout while a bare `appendHtml` lets Qt lay out
  incrementally. Batch a burst, never a unit.
- **Don't** make the five views lazy on a 250ms startup saving. `MainWindow`
  builds them all eagerly and it costs 283ms of a 457ms time-to-window, but
  only on a cold launch, and the user is looking at a model list by then.
  Trading an unperceived launch cost for a 140ms hitch on the first Settings
  click is a straight loss.
- **Don't** put Ink Primary on a saturated fill. It was the app's most
  prominent control reading at 2.37:1 under the current palette — 3.03:1 on
  Ember and 2.19:1 on Amber — and the fix was never a new token. It was
  applying the rule the loading pill had followed all along. See The
  Ink-on-Fill Rule.
- **Don't** put a level colour on a card-level surface. The Logs console is on
  `bg_primary` for a measured reason, not a stylistic one, and the moment it is
  moved up a rung Ember measures 4.29:1 and 3.82:1 there. If a log line needs a
  colour the ground cannot carry, the surface is wrong, not the colour.
- **Don't** keep a colour in the palette for a component that no longer
  exists. Engine Green sat in `theme.py` and DESIGN.md for years after the
  filled engine pill it was reserved for was replaced by a text chip; a
  reserved colour is a claim about the future that nobody is keeping.
- **Don't** treat a high share of a frame budget as a performance problem
  without reading the wall clock. The card shadows are 78% of a scroll frame
  and the frame still lands in 12.9% CPU against a flick whose duration does
  not change. Measure the user's experience, then the ratio.
