---
name: FrontierSQL
description: A conversational analyst in the familiar two-pane chat-app layout, where every answer shows the SQL that ran and why it was safe.
colors:
  surface: "#ffffff"
  sidebar: "#f8f8f7"
  raised: "#efefee"
  code: "#f6f6f5"
  ink: "#141416"
  ink-dim: "#55565c"
  ink-faint: "#6c6d74"
  line: "#e4e4e2"
  accent: "#9a5a1f"
  accent-soft: "#fbf1e4"
  ok: "#2c7a56"
  surface-dark: "#212122"
  sidebar-dark: "#18181a"
  raised-dark: "#303033"
  code-dark: "#1b1b1d"
  ink-dark: "#ececee"
  ink-dim-dark: "#b2b3b9"
  ink-faint-dark: "#8f9097"
  line-dark: "#343437"
  accent-dark: "#e0a35a"
  accent-soft-dark: "#3a2c1a"
  ok-dark: "#5cbb8e"
  chart-steel-blue: "#3b6e8c"
  chart-violet: "#6e5a9c"
  chart-teal-green: "#3b8c6e"
  chart-wine: "#8c3b6e"
  chart-olive: "#6e8c3b"
  chart-indigo: "#3b4f8c"
  chart-purple: "#7a3b8c"
  chart-cyan-teal: "#3b8c9e"
typography:
  display:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', ui-sans-serif, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  display-home:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', ui-sans-serif, system-ui, sans-serif"
    fontSize: "50px"
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: "-0.03em"
  headline-home:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', ui-sans-serif, system-ui, sans-serif"
    fontSize: "32px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  stat:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', ui-sans-serif, system-ui, sans-serif"
    fontSize: "32px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.025em"
    fontFeature: "'tnum'"
  title:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', ui-sans-serif, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', ui-sans-serif, system-ui, sans-serif"
    fontSize: "15.5px"
    fontWeight: 400
    lineHeight: "28px"
  ui:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', ui-sans-serif, system-ui, sans-serif"
    fontSize: "13.5px"
    fontWeight: 500
    lineHeight: 1.5
  meta:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', ui-sans-serif, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.5
  code:
    fontFamily: "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.625
rounded:
  lg: "8px"
  xl: "12px"
  2xl: "16px"
  3xl: "24px"
  composer: "28px"
  full: "9999px"
spacing:
  1: "4px"
  2: "8px"
  3: "12px"
  4: "16px"
  5: "20px"
  6: "24px"
  sidebar: "272px"
  column: "768px"
  header: "52px"
components:
  composer:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.ui}"
    rounded: "{rounded.composer}"
    padding: "8px 8px 8px 20px"
  button-send:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    rounded: "{rounded.full}"
    size: "36px"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    typography: "{typography.ui}"
    rounded: "{rounded.full}"
    padding: "8px 16px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-faint}"
    rounded: "{rounded.lg}"
    padding: "4px 8px"
  button-ghost-hover:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
  user-bubble:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.3xl}"
    padding: "10px 16px"
  example-chip:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.ui}"
    rounded: "{rounded.2xl}"
    padding: "12px 16px"
  sidebar-row:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.ui}"
    rounded: "{rounded.xl}"
    padding: "8px 36px 8px 10px"
  sidebar-row-current:
    backgroundColor: "{colors.raised}"
  menu-item:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.ui}"
    rounded: "{rounded.xl}"
    padding: "8px 12px"
  input-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.ui}"
    rounded: "{rounded.xl}"
    padding: "8px 12px"
  result-frame:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.xl}"
  alert-banner:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.ui}"
    rounded: "{rounded.xl}"
    padding: "12px 16px"
  sql-block:
    backgroundColor: "{colors.code}"
    textColor: "{colors.ink}"
    typography: "{typography.code}"
    rounded: "{rounded.lg}"
    padding: "10px 12px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.full}"
    padding: "10px 20px"
  button-outline-small:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.full}"
    padding: "6px 14px"
  showcase-window:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.2xl}"
  terminal-block:
    backgroundColor: "{colors.code}"
    textColor: "{colors.ink}"
    typography: "{typography.code}"
    rounded: "{rounded.xl}"
    padding: "14px 16px"
  theme-toggle:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-faint}"
    rounded: "{rounded.full}"
    padding: "4px"
  theme-toggle-current:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
---

# Design System: FrontierSQL

## Overview

**Creative North Star: "The Familiar Chat, Opened Up"**

The app wears the category-standard chat-app layout of Claude.ai and ChatGPT, played straight and pinned by the owner: chats listed in a left sidebar, a settings button pinned bottom-left, a centered conversation column, a rounded pill composer at the bottom. Convention is the commitment. Nobody has to learn the layout, so all the attention goes to the one thing this product does differently: every answer carries a single quiet verification line that opens into the plan, the exact SQL that ran, the step timings and every result check.

The material is neutral and soft. A white conversation pane sits beside a sidebar one step greyer; near-black ink; rounded corners everywhere (8px to 28px, plus full pills and circles); hairline borders instead of fills for containers; two soft shadows, used only on things that float. Color is almost absent. Amber appears only for focus, warnings, errors and destructive or rejected states. Green appears only as the "validated read-only" tick and the ready-database dot. Charts have their own muted series palette that never borrows the alert hue.

Density is that of a reading app, not a dashboard: a 768px column, 15.5px answer prose on a 28px line, results framed in hairline cards below the prose. Dark mode is a full mirror of the same tokens, following the system by default and switchable from the settings menu.

**Key Characteristics:**
- Two-pane chat layout: 272px sidebar, centered 768px conversation column, composer anchored at the bottom.
- User turns are grey rounded bubbles on the right; assistant answers are unboxed prose on the left.
- One verification line above every answer, opening into plan, SQL, steps and checks.
- Neutral greys plus two signal colors: amber for attention, green for validated.
- IBM Plex Sans for everything people read; JetBrains Mono only for SQL, identifiers and timings.
- Soft rounded geometry; hairline borders; shadows only on floating layers.

## Colors

A neutral grey world with two meaning-carrying signals and a separate muted chart palette. Every role exists in light and dark; the `-dark` tokens replace their light twins under `prefers-color-scheme: dark` or an explicit dark choice.

### Primary
- **Near-Black Ink** (`ink`, `ink-dark`): Body text, headings, and the filled controls: the round send/stop button and the primary dialog button. In dark mode the same role inverts to near-white, so filled buttons become light circles on a dark pane.

### Secondary
- **Amber** (`accent`, `accent-dark`): Focus rings (2px outline, 2px offset), the text caret, warning and error icons, failed trace segments and retry counts, the rejected-database status, the chat delete confirmation, and the character counter at its limit. The light value is darker so it clears 4.5:1 as text on white.
- **Amber Wash** (`accent-soft`, `accent-soft-dark`): Fill for error banners, warning notes and text selection, always paired with a 40% amber border.

### Tertiary
- **Validated Green** (`ok`, `ok-dark`): Only the shield tick on a validated read-only answer, a passed check, the "Copied" tick, and the ready-database dot.

### Neutral
- **Pane White** (`surface`, `surface-dark`): The conversation pane, composer, menus, dialogs and table frames.
- **Sidebar Grey** (`sidebar`, `sidebar-dark`): The chat list, one step off the pane so the two regions separate without a heavy rule.
- **Raised Grey** (`raised`, `raised-dark`): User bubbles, hovered and current rows, hovered ghost buttons, the settings avatar disc.
- **Code Grey** (`code`, `code-dark`): The SQL block, table header row, keyboard keys, and table row hover.
- **Dim Ink** (`ink-dim`, `ink-dim-dark`): Secondary text: the empty-state lead, section titles, labels, icons in menus.
- **Faint Ink** (`ink-faint`, `ink-faint-dark`): Metadata, placeholders, timings, axis ticks, inactive icons. Still passes AA on its surface.
- **Hairline** (`line`, `line-dark`): Every border and divider, chart gridlines and axes, scrollbar thumbs.

### Chart series
- **Steel Blue, Violet, Teal Green, Wine, Olive, Indigo, Purple, Cyan-Teal** (`chart-*`): The eight series colors, assigned in that order. Single-series charts use Steel Blue only.

### Named Rules
**The Two Signals Rule.** Amber means "look here" (focus, warning, error, destructive, rejected); green means "validated". No other hue carries meaning in the interface, and neither is used for decoration.

**The Quiet Chart Rule.** Chart series never use amber, orange or red. A routine chart must not read as an alert. Series colors are mid-tone and legible on both the white and the near-black pane.

**The Mirror Rule.** Every surface, ink, line and signal token has a dark twin, and components reference roles, never literal hex. A new component that looks right in only one theme is unfinished.

## Typography

**Body Font:** IBM Plex Sans (with Segoe UI, system-ui fallback), weights 400 / 500 / 600
**Mono Font:** JetBrains Mono (with ui-monospace, Menlo, Consolas), weights 400 / 500

**Character:** Plex Sans carries the whole conversation in one calm, slightly technical voice; JetBrains Mono appears only where the text is literally machine text, so its presence signals "this is exactly what ran".

### Hierarchy
- **Display** (600, 30px / 26px under 640px, 1.25, -0.025em): The empty-state greeting only.
- **Display, homepage** (`display-home`: 600, 50px / 34px under 640px, 1.12, -0.03em, balanced): The homepage headline only. The chat app never uses it.
- **Headline, homepage** (`headline-home`: 600, 32px / 26px under 640px, 1.25, -0.025em): Homepage section heads. The closing band's head sits between the two at 34px / 28px. Homepage leads under these are `ink-dim` at 16px on a 28px line (16.5-17.5px under the headline), max 38rem.
- **Stat** (600, 32px, line-height 1, tabular figures): The single-value result card.
- **Title** (600, 17px): Dialog titles; help-panel section heads use 600 at 15px.
- **Body** (400, 15.5px on a 28px line, max 42rem): Assistant answer prose. User bubbles use 15px with relaxed leading.
- **UI** (400 or 500, 14px): Sidebar rows, menu items, buttons, form fields, banners, example chips. The composer text is 15.5px (16px on mobile to stop iOS zoom).
- **Label** (500, 13.5px, sentence case): The verification headline, status labels such as "Not answerable from this database", plan labels.
- **Meta** (400, 12-13px, `ink-faint`): Sidebar date groups, menu group labels, row counts, footnotes, chart ticks (12px).
- **Code** (JetBrains Mono 400, 13px, 1.625): SQL. Mono at 12.5px for step names, check codes and elapsed times; schema identifiers at 13-13.5px.

### Named Rules
**The Machine Text Rule.** Monospace is for SQL, identifiers, check codes, request ids and timings, nothing else. Headings, labels, buttons and prose are always Plex Sans.

**The Sentence Case Rule.** Every label, group heading and button is sentence case at normal tracking. No uppercase, no letter-spaced small labels.

**The Tabular Rule.** Numbers in tables, stats, counters and timings use tabular figures, and numeric table columns are right-aligned with fixed decimals so points line up.

## Layout

A full-height two-pane shell. On desktop (768px and wider) the sidebar is a 272px column with a hairline right border, collapsible to nothing; when collapsed, sidebar and new-chat icon buttons appear in the 52px header. Below 768px the sidebar becomes a drawer over a 40% black scrim, opened from a menu icon in the header.

The conversation lives in a centered column (max 768px, 16px side padding, 24px from 640px up). Each turn has 20px vertical padding; the user bubble is right-aligned at max 75% width (85% on mobile), and the answer stack below it uses a 16px gap: verification line, prose, warnings, table, chart, copy action. The composer is pinned below the scroll area in the same column, with a one-line 12px footnote under it; a 20px gradient from the pane color fades content under the header.

The empty state centers vertically: greeting, a two-line lead, the composer 32px below, a two-column grid of example questions (one column on mobile) 16px below that, and a quiet "How answers are checked" link.

Spacing follows a 4px rhythm (4 / 8 / 12 / 16 / 20 / 24 / 32), with the half-steps 6px and 10px used for compact control padding.

### Homepage
The project homepage (at `/`; the chat app lives at `/chat/`) is the same world laid out as a reading page, not a second style. A sticky 56px top bar on the pane color gains its hairline only once the page scrolls. Content sits in a 72rem container (16px / 24px side padding); the hero is centered in 46rem, with the headline, lead, the two action pills and one quiet faint line, then the replay window starting above the fold. Sections open with 96px of space (128px from 640px up) and a left-aligned section head. From 1024px most sections split 5:7: explanatory prose left, the evidence (an open verification panel, a table, the terminal) right; below that they stack. Supporting lists use hairline-topped definition cells in a two-column grid rather than cards. A closing band, separated by a full-width hairline, repeats the actions centered; the footer sits on `sidebar` grey above a hairline.

## Elevation & Depth

Flat by default. The pane, sidebar and result frames separate by tone and hairline borders, not shadow. Exactly two shadows exist, and both mark something that floats above the conversation.

### Shadow Vocabulary
- **Composer lift** (`box-shadow: 0 1px 2px rgb(0 0 0 / 0.04), 0 4px 16px rgb(0 0 0 / 0.06)`; dark: 0.3 / 0.25): The composer pill only, so the input reads as sitting above the scrolling transcript.
- **Menu float** (`box-shadow: 0 2px 6px rgb(0 0 0 / 0.06), 0 12px 32px rgb(0 0 0 / 0.12)`; dark: 0.3 / 0.45): The settings menu, dialogs, chart tooltips, the mobile drawer, and the inline delete confirmation.

- **Showcase window** (menu float): The homepage replay window. It is the one non-floating frame allowed a shadow, because it presents the whole app as an object set onto the page; nothing inside it gains a shadow beyond the composer lift it already carries, and no other homepage frame is lifted.

A horizontally scrolling table shows soft edge shadows that ride the scroll position, indicating columns out of view.

### Named Rules
**The Floating-Only Rule.** Only layers that sit above the conversation (composer, menus, dialogs, tooltips, drawer) get a shadow. Cards, banners and table frames stay flat with a hairline border. The single exception is the homepage showcase window, which stands in for the whole app.

## Shapes

Soft and consistently rounded, scaled by size: 8px for small ghost buttons, the SQL block and icon buttons; 12px for result frames, banners, fields, sidebar rows and menu items; 16px for example chips, the settings menu and dialogs; 24px for user bubbles; 28px for the composer pill; fully round for the send button, primary and retry buttons, status dots and avatar discs. Borders are always 1px hairlines in `line`; the amber border appears only on alert surfaces, at 40% opacity.

Icons are one authored family: 24px grid, 1.75 stroke, round caps and joins, no fills, drawn at 15-18px.

## Components

### Composer
The heart of the screen: a 28px-radius pill on the pane color with a hairline border and the composer lift. The textarea grows to 200px, then scrolls. On focus the border darkens to `ink-faint` at 60%; the textarea itself shows no ring. The trailing 36px round ink button sends (25% opacity when empty) and becomes a stop square while an answer is running. A character counter appears only from 400 of 500 characters, turning amber at the limit.

### Buttons
- **Shape:** Pills and circles for actions (9999px); 8px for small ghost actions; 12px for full-width rows.
- **Primary:** Ink fill, pane-colored text, 8px 16px, medium weight. Used for the send button and the dialog's confirm action; never more than one per view.
- **Hover / Focus:** Filled buttons drop to 85% opacity on hover; ghost buttons gain the `raised` fill and full ink. Focus is the global 2px amber outline, 2px offset. Disabled is 25-60% opacity with a not-allowed cursor.
- **Ghost:** Transparent, `ink-faint` or `ink-dim` text, often with a 15-16px icon: Copy answer, Copy SQL, CSV, header icon buttons.
- **Outlined pill:** Hairline border on the pane color, 13px medium: Retry in error banners, "See what's in this database". Hover fills with `raised` at 60%. The homepage uses it at two sizes: 15px medium at 10px 20px beside the ink pill ("View on GitHub", with a 17px icon), and 13px medium at 6px 14px for in-frame toggles ("Show all 28").
- **Homepage actions:** The ink pill grows to 15px at 10px 20px for "Try the demo"; it always pairs with the large outlined pill, never a second filled color. Inline text links are ink or inherit their text color, underlined with a `line` decoration at 4px offset that darkens to `ink-faint` on hover.

### User bubble and answer
User turns are a `raised` bubble (24px radius, 10px 16px) right-aligned. Assistant turns have no container: prose in body type, then framed results. While working, three 6px dots breathe in sequence beside "Writing and validating SQL" and an elapsed-seconds counter.

### Verification line (signature)
One ghost row above every answer: a 16px shield icon (green when validated, amber on a failure or warning, faint otherwise), a medium-weight headline ("Validated read-only SQL", "What was attempted"), faint "· N checks passed · repaired N×" parts, the total time in mono, and a chevron that rotates 90° when open. It opens into a hairline-bordered 12px-radius panel with sections Plan (a label/value grid), SQL that ran (code block with Copy SQL), Steps (the trace strip) and Result checks, then a 12.5px metadata footnote. Closed by default, never empty. Warning-severity checks are also shown beside the answer in an amber note, so they never hide behind the summary.

### Trace strip
An 8px rounded bar with each backend step's segment proportional to its duration; segments are faint ink, skipped steps hairline, failed steps amber. Repeated steps get a thin amber "redo lane" under the bar. Step names in mono with timings sit in a wrapping row beneath.

### Result table
A 12px-radius hairline frame. The sticky header row is `code` grey with 13px medium dim labels carrying units; body 13.5-14px tabular. Rows divided by hairlines, hover tint in `code`. A footer row shows row count and execution time plus a CSV ghost button. Capped at 26rem height; horizontal overflow shows scroll shadows.

### Chart and stat
Charts sit in a 288px-tall hairline frame (12px radius) with `line` gridlines and axes, 12px faint ticks that carry units, and series in the chart palette. Lines are 1.75px. Tooltips use the pane color, hairline border, 8px radius and menu float. A single value renders as a stat card: 32px semibold figure over a 13px faint label.

### Sidebar and settings menu
- **Sidebar:** The product name, a collapse icon, a "New chat" row, then chats grouped by date under 12px faint group labels. Rows are 12px-radius, 14px; the current row is `raised`, hovered rows `raised` at 60%. A trash icon reveals on hover (always visible on the current row and on mobile) and asks for an inline amber "Delete" confirmation.
- **Settings button:** Pinned at the bottom above a hairline: a 32px `raised` disc with a database icon and a status dot (green ready, amber rejected, grey unavailable), the database name in 14px medium, dialect and status in 12.5px, and an up/down chevron.
- **Settings menu:** Opens upward with a 4px rise-in (140ms). 16px radius, hairline, menu float, 6px inner padding. Groups Database, Theme, then help and source links, separated by inset hairlines. Theme is a three-up segmented grid (Light, Dark, System) with the current choice on `raised`.

### Inputs / Fields
- **Style:** 12px radius, hairline border, pane fill, 8px 12px, 14px text; the connection URL field is mono 13px.
- **Focus:** Border darkens to `ink-faint`; no ring inside the field.
- **Error:** Amber border plus an amber 13px hint beneath; neutral hints are 13px faint.

### Dialogs
Native modal dialogs centered on a 40% black backdrop: 16px radius, hairline, menu float, max 32rem (48rem wide variant), 24px padding, 17px semibold title, faint close icon. They rise in like the menu.

### Banners
Errors and warnings are 12px-radius amber-wash panels with a 40% amber border, an 18px amber alert icon, a medium ink title, dim body, an optional mono request id and an outlined pill Retry that counts down when the server asks for a wait.

### Homepage showcase and evidence
- **Replay window (signature):** A full miniature of the app, sidebar and pane, in a 16px-radius hairline frame on the pane color with menu float, inert to the pointer. When its composer scrolls fully into view it types the recorded question (with the amber caret), sends it, breathes the working dots for the recorded duration, then reveals verification line, prose, table and chart in turn (500ms fade and 4px rise, 320ms apart). Every part is laid out from the start so the frame never changes height. Reduced motion shows the finished answer. A 13px faint caption beneath states what was recorded and when, with a ghost Replay button.
- **Metric table:** The result-table frame reused for recorded numbers: `code` header with 13px medium dim labels, label column left, results right-aligned and tabular, ratios as "74/78" with the percentage faint in a fixed-width slot.
- **Ledger:** A result-table frame whose header strip is a `code` row carrying the green shield, a medium ink claim ("28 of 28 statements blocked") and faint run metadata with the run id in mono. Rows pair the statement in mono 13px ink with the response in 14px dim, stacking below 768px. It shows six rows, with a footer for count, source link and a small outlined pill to expand.
- **Terminal block:** A 12px-radius hairline frame on `code`, with a title row (13px faint "Terminal" plus a ghost Copy) above mono 13px commands on a 1.7 line; trailing shell comments are faint and drop to their own line on mobile.
- **Theme toggle:** A pill radiogroup in the footer: a hairline pill on the pane color with 4px padding holding three 32px round icon buttons (sun, moon, monitor at 16px). The current choice is `raised` with ink; the others faint, darkening on hover. It mirrors the settings menu's Light, Dark, System choice.
- **Numbered steps:** 28px `raised` discs with a 12.5px medium tabular numeral beside a 15px medium step name and a faint 13px qualifier.

## Do's and Don'ts

### Do:
- **Do** keep the chat-app layout conventional: sidebar left, settings bottom-left, centered column, pill composer at the bottom.
- **Do** put a verification line above every answer, including failures, and keep warnings visible beside the answer.
- **Do** reference color roles (`surface`, `raised`, `ink-dim`, `line`, `accent`) so every component works in both themes.
- **Do** use amber only for focus, warnings, errors, destructive confirmation and rejected state, and green only for validated, passed and ready.
- **Do** use JetBrains Mono for SQL, identifiers, check codes and timings, and tabular figures for every number in a table or stat.
- **Do** frame results (tables, charts, panels) with a 1px hairline and 12px radius, and reserve shadows for floating layers.
- **Do** honor reduced motion: animations (the 140ms rise-in, the breathing dots) collapse to instant.

### Don't:
- **Don't** use amber, orange or red in chart series.
- **Don't** box assistant answers in a bubble or card; only the user's turn is a bubble.
- **Don't** set headings, labels or buttons in monospace, uppercase or letter-spaced small caps.
- **Don't** add shadows to cards, banners or table frames.
- **Don't** introduce a second filled-button color or a brand-colored primary; filled actions are ink.
- **Don't** use emoji or font glyphs as icons; draw from the authored 1.75-stroke icon family.
