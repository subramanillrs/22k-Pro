---
version: alpha
name: "22k-Pro"
description: "A Chennai gold-market instrument panel built around trusted fix times, legible prices, and practical buying tools."
colors:
  primary: "#a97f34"
  background: "#f8f4ea"
  surface: "#ffffff"
  ink: "#1c1712"
  success: "#337a4c"
  danger: "#ad3d30"
typography:
  display:
    fontFamily: "Fraunces, Iowan Old Style, Georgia, serif"
  sans:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans Tamil', sans-serif"
  data:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans Tamil', sans-serif"
rounded:
  DEFAULT: "14px"
  sm: "8px"
  md: "14px"
  lg: "22px"
spacing:
  page-max: "600px"
  section-gap: "16px"
components:
  button: { radius: "9999px", focus: "2px gold outline with 3px offset" }
  card: { radius: "22px", surface: "theme-aware paper-raised" }
  input: { radius: "8px", height: "42px" }
---

# 22k-Pro Design System

## Overview

### Creative North Star

The app should feel like a compact Chennai jeweller's rate ledger brought onto a phone: warm paper, a restrained gold rule, and the AM/PM fix tape as the distinctive market artifact. Keep the live benchmark and its timestamp more prominent than analytics.

### Product context and register

- **Audience and primary job:** Chennai gold buyers and holders checking a benchmark, estimating a purchase, or tracking personal lots.
- **Target market(s) and evidence:** India; the product explicitly tracks Chennai rates, GST, rupees, and sovereign weights in `README.md`.
- **Locale(s) and language policy:** English default with Tamil available for core navigation and common controls; market data, source names, and technical indicators retain canonical values/names.
- **Usage scene:** Frequent glances on narrow phones, often during market updates; preserve one-column reading and reachable actions.
- **Register:** Product instrument panel, not a marketing landing page.
- **Memorable signature:** Morning/Evening fix timeline connected to the current per-gram and sovereign benchmark.
- **Restraint:** Charts, source comparisons, calculators, alerts, portfolio, and diagnostics remain optional layers below the rate.
- **Anti-references:** Trading-terminal neon, generic fintech blue, decorative bullion photography, and motion that obscures a changing value.

## Colors

The existing CSS custom properties are the runtime source of truth. Light mode uses paper `#f8f4ea`, white raised surfaces, umber ink `#1c1712`, and antique gold `#a97f34`; green `#337a4c` and red `#ad3d30` retain their directional meaning. Dark and OLED themes preserve these semantic roles with their existing theme overrides. Never communicate source health or price direction by color alone.

## Typography

Fraunces is reserved for the brand and headline price; Inter carries controls, labels, and compact tables. Price data uses tabular numerals. Tamil falls back through the system stack to Noto Sans Tamil; allow its line height and word length to wrap without clipping. Keep technical acronyms such as IBJA, RSI, and EMA unchanged.

## Layout

The page is a single, naturally scrolling column capped at 600px, with safe-area padding and a 16px section rhythm. Keep quick navigation compact and sticky only while scrolling; anchor targets receive scroll offset. Dense data may scroll inside its own table surface; never constrain the full page to viewport height.

## Elevation & Depth

Use tonal paper surfaces, fine rules, and the existing low directional shadows for cards. Blur is reserved for the compact navigation/status surfaces. Avoid adding elevation to every data row.

## Shapes

Existing 8px form corners, 14px controls, and 22px feature cards establish the shape grammar. Chips and compact actions remain pill-shaped. Focus uses a visible gold outline and offset in every theme.

## Components

### Foundational visual states

Controls retain hover, active, keyboard-focus, selected, disabled, and busy states. Respect reduced-motion preferences. Stale, offline, and disagreement states include explanatory text as well as semantic color.

### Buttons and actions

Primary actions use the existing gold treatment; secondary actions are quiet outlines or chips. Busy states do not change button dimensions. Data import is additive/merge-only and never silently replaces holdings.

### Navigation and data display

Use native links for section jumps and native tables for read-only history. Reserve the current-price region for the latest verified feed and its age. Charts are illustrative; source values and timestamps remain textually accessible.

### Forms and overlays

Keep existing native calculator and date controls. Presets and portfolio backups remain in local browser storage/files; no portfolio data is sent to a server. Use the shared toast/status treatment for completion and errors.

### Iconography

Use the existing inline stroke icons and keep labels/accessible names on actions whose icon is not self-evident.

### Motion

Use short transitions for interaction and one restrained pulse when the rate genuinely changes. Reduced motion disables nonessential animation.

### Content and data visualization

Use concise sentence-case labels, `₹` and Indian number grouping, and IST/source timestamps. Distinguish verified values from estimates and historical ranges.

## Do's and Don'ts

- **Do:** Keep the rate, source freshness, and AM/PM fixing context easy to scan.
- **Do:** Preserve existing calculator, alerts, chart, comparison, portfolio, export, and offline behavior when adding tools.
- **Don't:** Describe a scheduled scrape as guaranteed live data.
- **Don't:** replace the warm gold-led visual identity with generic neon dashboards.
