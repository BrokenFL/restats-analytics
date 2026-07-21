# Design QA

## Source visual truth

- Six-card dashboard request: `/tmp/codex-remote-attachments/019f84c5-50c3-7233-a093-224fc9fad0c5/17FFC1C9-9DDD-4DD4-BBE0-795894D6DC60/1-Photo-1.jpg`
- Missing-stat social card: `/tmp/codex-remote-attachments/019f84c5-50c3-7233-a093-224fc9fad0c5/17FFC1C9-9DDD-4DD4-BBE0-795894D6DC60/2-Photo-2.jpg`

## Rendered implementation

- Dashboard capture: `output/playwright/restats-audit-2026-07-21/six-primary-cards-focused-final.png`
- Social-report capture: `output/playwright/restats-audit-2026-07-21/median-dom-fix-desktop.png`
- Desktop viewport: 1267 by 713 CSS pixels
- Mobile viewport check: 390 by 844 target, 386-pixel rendered viewport
- State: Palm Beach, monthly report, June 2026

## Full-view comparison evidence

Each user screenshot was opened in the same comparison input as its matching rendered implementation. The dashboard now presents six primary MLS cards in a balanced three-by-two grid while keeping Market Grade in the side-panel Market Pulse only. The social report preserves the approved square editorial layout and replaces the unavailable average-DOM statistic with the existing Median DOM metric.

## Focused-region comparison evidence

- Primary dashboard cards: Sold Count, Avg Sold Price, Median Sold Price, Active Inventory, Months Supply, and Median DOM are all populated for Palm Beach June 2026.
- Supporting section: The disclosure is labeled `Show supporting metrics`; there is no Market Grade card, grade formula, grade read, or component-score block in the main column.
- Social statistic row: `137 MEDIAN DOM` is rendered with `down 11.3% YOY`; the caption and alt text both say median days on market.

## Fidelity surfaces

- Fonts and typography: The existing ReStats font stack, metric hierarchy, weights, and numeric emphasis are preserved. A small primary-label adjustment prevents truncation at the desktop three-column width.
- Spacing and layout rhythm: Six primary cards fill two complete rows with consistent gaps and alignment. The Market Pulse remains visually separate in the right column.
- Colors and visual tokens: Existing white cards, navy text, teal positive states, red negative states, borders, and shadows remain unchanged.
- Image quality and asset fidelity: The approved ivory architectural raster background remains sharp and correctly scaled in the social export.
- Copy and content: No social caption or alt text references average DOM or displays `N/A`. Market Grade appears only in the existing side-panel experience.

## Findings and comparison history

1. P1: The source screenshot showed `AVG DAYS ON MARKET` as unavailable because that field was absent from cached monthly summaries. Fixed by using the established `median_dom` metric and its year-over-year comparison throughout the image, caption, and alt text. Post-fix evidence shows `137 MEDIAN DOM` and `down 11.3% YOY`.
2. P2: Adding the sixth primary card initially caused several labels to ellipsize at the desktop width. Fixed by tightening the card icon track, gap, padding, and primary-label size. Post-fix DOM measurements show every primary label's scroll width equal to its client width.
3. Mobile follow-up: At the phone breakpoint the primary grid becomes one column, every label fits, and document width equals viewport width, so there is no horizontal overflow.

## Interaction and console checks

- Tested City, Date Range, Month, and Social Report controls.
- Confirmed the Palm Beach June report produces all six primary metrics and the corrected social asset.
- Confirmed the Instagram caption and alt text use Median DOM.
- Browser console error count: 0.

final result: passed
