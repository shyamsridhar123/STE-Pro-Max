---
# Modified for STE-Pro-Max from ATV-PaperBoard.
# Copyright (c) 2026 All-The-Vibes / atv-paperboard contributors.
# SPDX-License-Identifier: Apache-2.0
# Source commit: 4b068bcab8e4dc105f0ef975ee224564f5d63383.
# Changes: offline system fonts, safe metadata, native STE-Pro-Max branding.
version: alpha
name: paperboard
description: Default design for atv-paperboard gallery and emitted artifacts. Dialed-back neubrutalism — dark editorial surfaces, restrained accent, no decorative excess.
colors:
  primary: "#7170FF"
  secondary: "#5E6AD2"
  accent: "#F1B13B"
  background: "#08090A"
  surface: "#0E0F12"
  border: "#1A1B21"
  foreground: "#F7F8F8"
  muted: "#8A8F98"
  danger: "#C97070"
  success: "#7FAE6E"
typography:
  body:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.55
  heading:
    fontFamily: "Georgia, Times New Roman, serif"
    fontSize: 28px
    fontWeight: 510
    lineHeight: 1.15
    letterSpacing: -0.02em
  mono:
    fontFamily: "ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: 4px
  md: 8px
  lg: 12px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 48px
---

<!-- Modified for STE-Pro-Max: only supported local token syntax is validated.
No upstream Node lint, visual doctrine audit, or STE compliance is claimed. -->

# Paperboard

Default design system for atv-paperboard. The aesthetic is dialed-back neubrutalism on a dark editorial canvas: high-contrast structure, decisive typography, restrained accent, no rainbow palettes or thick drop-shadows.

## Do

- Use `{colors.foreground}` for primary text and headings.
- Use `{colors.primary}` for emphasis, interactive states, and accent borders.
- Use `{colors.accent}` sparingly — status callouts, errors, pull quotes.
- Prefer `{typography.body}` for prose; `{typography.mono}` for code, labels, and metadata.
- Keep spacing on the `{spacing.md}` / `{spacing.lg}` scale for card interiors.
- Border thickness: 1px for dividers, layered surfaces (background → surface → surface-2) define depth.

## Don't

- Don't use drop-shadows by default. Borders and layered surfaces define depth here.
- Don't use `backdrop-filter: blur` on any surface — glassmorphism is banned (impeccable doctrine).
- Don't apply gradient fills to text (`background-clip: text` with a gradient is banned).
- Don't use a colored `border-left`/`border-right` stripe wider than 1px as a side-stripe on cards, list items, callouts, or alerts.
- Don't nest cards inside cards. Gallery frame and artifact card are sibling component definitions, not a nesting prescription — flatten the hierarchy in templates.
- Don't decorate with generic AI emoji (✨ 🚀 ⚡ 🎯 etc.). Use mono glyphs, status dots, and typography for emphasis.
- Don't mix more than 3 type sizes on one artifact.
- Don't apply `{colors.accent}` to more than 15 % of visible surface area.
- Don't use decorative background patterns in the default tier.

## Colors

Foreground (`{colors.foreground}`) anchors text. Primary (`{colors.primary}`) is the indigo accent used for interactive borders, links, and emphasis panels. Accent (`{colors.accent}`) is the rose reserved for status and warnings. Background (`{colors.background}`) and surface (`{colors.surface}`) are near-black — pure `#000000` would be too stark; `#08090A` and `#0E0F12` give subtle depth between the page and elevated surfaces.

Muted (`{colors.muted}`) for secondary text and metadata rows.

## Typography

System sans-serif for body text, Georgia for display headings, and system monospace for code and labels. Heading weight 510 (slightly heavier than regular), body weight 400. Letter-spacing tightened on headings (`-0.02em`) for the neubrutalist compression feel.

## Components

Gallery frame: flat card, `{colors.border}` 1px outline, `{rounded.lg}` radius, `{spacing.md}` padding, `{colors.surface}` background.
Artifact card: same as gallery frame; heading row uses `{colors.foreground}`, metadata row uses `{colors.muted}`.
Status badge: transparent background, `{colors.primary}` text, 1px `{colors.primary}` outline, `{rounded.sm}` radius, `{spacing.xs}` padding.
Code block: `{colors.background}` background (deeper than surface), `{colors.border}` 1px outline, `{typography.mono}`.
