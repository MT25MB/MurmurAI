---
name: Murmur AI
description: A dark, high-contrast instrument panel for a voice-controlled local agent.
colors:
  obsidian: "#080a0f"
  surface: "#10141b"
  surface-2: "#1b1f28"
  border: "#2d333e"
  muted: "#a0a5ae"
  ink: "#f1f3f9"
  blue: "#5598f9"
  blue-fill: "#156cdd"
  blue-deep: "#0c2c5a"
  red: "#f05653"
  red-fill: "#d01c29"
  red-deep: "#4a0e13"
typography:
  display:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "3.6rem"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  title:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "2.25rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.4
  telemetry:
    fontFamily: "ui-monospace, SF Mono, Cascadia Code, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "4px"
  md: "8px"
  lg: "14px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  xxl: "48px"
  xxxl: "64px"
components:
  button-primary:
    backgroundColor: "{colors.blue-fill}"
    textColor: "#ffffff"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "14px 24px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "{spacing.lg}"
---

# Design System: Murmur AI

## Overview

**Creative North Star: "The Instrument Panel."** (Inferred from the incumbent `index.css` header, which already names the system "Instrument"; not a separate user choice.) The site reads as the readout of a calm, precise machine: flat obsidian surfaces, one-pixel hairlines, a single blue signal colour, and red reserved for the moment the agent acts. Nothing glows for attention; colour is information, not ornament.

Density is moderate and editorial. Sections breathe, but inside a section the grouping is tight: a heading, a short factual paragraph, then one demonstration (a live HUD readout, an agent trace, a requirements table). Copy is plain and technical without being cold — the product's own words, never marketing superlatives.

**Key Characteristics:**
- Flat, tonal layering instead of elevation shadows.
- One accent in use at a time: blue for navigation and primary action, red only for execution/alert state.
- Monospace is reserved for actual code, telemetry, and measurements — never used as a "technical" costume.
- Motion is a single authored state machine (the HUD waveform), with reduced-motion honoured everywhere.

## Colors

A near-monochrome obsidian ramp with two signal accents, both measured for white-text contrast.

### Primary
- **Signal Blue** (`#5598f9`): links, active states, focus rings, and the primary action. Derived from the logo's navy hue (258).
- **Action Blue Fill** (`#156cdd`): filled primary buttons; white text measures 4.98:1.

### Secondary
- **Execution Red** (`#f05653`): execution and alert state only — never a generic accent or decoration.
- **Execution Red Fill** (`#d01c29`): filled alert/execution surfaces; white text measures 5.41:1.

### Neutral
- **Obsidian** (`#080a0f`): page canvas.
- **Surface** (`#10141b`) and **Raised Surface** (`#1b1f28`): panels and inset code blocks.
- **Hairline** (`#2d333e`): borders and dividers.
- **Ink** (`#f1f3f9`) and **Muted** (`#a0a5ae`): primary and secondary text.

### Named Rules
**The One Voice Rule.** Only one accent carries meaning in a viewport: blue for navigation/action, red for execution. Never use both as decoration in the same element.

**The Dead Colour Rule.** Soft-focus coloured blobs and gradient washes are not part of this system. A coloured surface earns its place by encoding state.

## Typography

**Display / Body Font:** Inter with system fallbacks (no downloaded webfont, no licensing risk).
**Label / Telemetry Font:** the system monospace stack, for code and measured data only.

**Character:** Quiet and legible. Tight tracking on headings, relaxed leading on body, unmistakable weight steps. Numbers in data are tabular so they align in columns.

### Hierarchy
- **Display** (weight 600, `clamp(2.25rem, 4vw, 3.6rem)`, line-height 1.05, tracking -0.03em): the single hero statement.
- **Title** (weight 600, `1.5–2.25rem`, line-height 1.15, tracking -0.02em): section headings.
- **Body** (weight 400, `0.875–1rem`, line-height 1.6, max measure 65–75ch): explanations.
- **Label** (weight 500, `0.875rem`, sentence case): controls and navigation.
- **Telemetry** (monospace, `0.6875–0.8125rem`, tabular numerals): code traces, model names, versions, measurements.

### Named Rules
**The Sentence-Case Rule.** Interface labels are sentence case. Uppercase and letter-spacing are reserved for short telemetry strings that are genuinely data, never for section eyebrows.

**The No Gradient Type Rule.** Emphasis comes from weight, size, or the single signal colour — not gradient text or a coloured highlight on one word.

## Layout

A 7xl (`max-width: 1280px`) centred container with `20px` gutters (`32px` from `sm`). Sections use `64–96px` vertical rhythm. The hero is a two-column grid at `lg` (`1.05fr / 0.95fr`) and a single column below. Capabilities is a `380px / 1fr` split that stacks on smaller screens; requirements use a horizontally scrollable table with a `min-width: 640px` inner table so data stays readable rather than clipped. Quick start uses two columns at `md`.

The spacing scale is `4 / 8 / 16 / 24 / 32 / 48 / 64px`. Inside a panel, padding is at least `16px`. Nested radii follow `R_inner = max(0, R_outer - padding)`.

## Elevation & Depth

Flat by default. Depth comes from tonal layering (canvas → surface → raised surface) and one-pixel hairline borders, not from diffuse shadows. A soft shadow may appear only as a response to a real state change (e.g. the HUD panel's resting depth), never as a zero-offset coloured halo.

### Named Rules
**The Flat-By-Default Rule.** No decorative blur blobs, glass panels, or hover lift. A surface is flat at rest and changes only by border or background on state.

## Shapes

Gentle, restrained cornering: `4px` for small chips and focus outlines, `8px` for buttons and controls, `14px` for panels. Borders are `1px solid` hairlines. The recurring silhouette is a flat rectangle with a crisp top divider and a small inset readout — a panel with a header, not a floating card.

## Components

### Buttons
- **Shape:** gently rounded (`8px`), `14px × 24px` padding for primary, `10px × 20px` for secondary.
- **Primary:** Action Blue Fill with white text; hover brightens once, `:active` gives a brief tactile press, `:focus-visible` draws a 2px Signal Blue ring with 3px offset.
- **Secondary / Ghost:** Surface background with a hairline border; the text colour shifts to Signal Blue on hover/focus, never the background.
- **States:** default, hover, focus-visible, active, disabled, loading, error, and success are all represented; disabled is 50% opacity with `not-allowed` cursor. Transitions are under 200ms with an ease-out curve; reduced motion removes them.

### Chips
- **Style:** flat Surface background, hairline border, `4px` radius, sentence-case text. They are facts (license, OS), not decoration.
- **State:** hover shifts the border to Signal Blue; no selected state unless the chip is genuinely interactive.

### Cards / Containers
- **Corner Style:** gentle (`14px`) with a `1px` hairline border.
- **Background:** Surface; inset code regions use Obsidian.
- **Shadow Strategy:** flat at rest; at most a soft, offset shadow on the single signature preview panel.
- **Internal Padding:** `24px` (`16px` at the smallest breakpoint).

### Tables
- **Style:** hairline row dividers, `16–20px` cell padding, row headers in Ink, data in Muted, sentence-case column heads.
- **Focus:** horizontally scrollable container with a visible focus affordance; never clip content to fit.

### Navigation
- **Style:** sticky, `64px` tall, Obsidian at 85% opacity with a hairline bottom border; brand mark plus a wordmark, section links, and one GitHub action.
- **Typography:** sentence-case labels, `0.875rem`, Ink at 70% opacity shifting to Signal Blue on hover/focus.
- **Mobile:** section links collapse; brand and GitHub action remain.

### Signature Component: HUD Readout
A flat bordered panel with a top chrome row (state dot, `murmur / agent`, version/telemetry), a canvas waveform, a state readout line in monospace, and a three-segment state track. Blue = listening, muted = thinking, red = executing. The waveform is the one authored motion on the page and becomes static under `prefers-reduced-motion`.

## Do's and Don'ts

### Do:
- **Do** keep the measured palette in `index.css` as the single source of truth; app and website use identical tokens.
- **Do** use monospace for code, model names, versions, and measurements, with tabular numerals.
- **Do** give every interactive element a visible `:focus-visible` ring and a real `:active` response.
- **Do** keep claims factual and sourced in the repository; say "local" only where the code is local.
- **Do** honour `prefers-reduced-motion` and keep text readable at 320px width.

### Don't:
- **Don't** add blurred coloured blobs, gradient washes, or gradient text.
- **Don't** put an uppercase eyebrow or section number above a heading; the heading carries its own weight.
- **Don't** repeat a metric in badges, stat strips, and section cards; one fact gets one home.
- **Don't** make every section the same icon-plus-heading-plus-text card grid.
- **Don't** hardcode a release version in a component; derive it or omit it.
- **Don't** use `!important` utility overrides to fight the token system; fix the token or the class.

_Provenance: tokens and component behaviour were extracted from `website/src/index.css` and `website/src/components/`. Descriptive names, the North Star label, and the named rules are inferences from that incumbent system, labeled because the user authorized proceeding from the brief._
