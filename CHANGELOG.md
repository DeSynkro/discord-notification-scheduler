# Changelog

## 1.4

### Added
- Cards and modals now have a frosted glass look with blur
- Space background with drifting glows that slowly shift around
- Cards and chips gently lift and glow on hover
- Items animate in with a staggered entrance on page refresh
- A gentle light ripple glides across the header
- Modals pop in with a smooth scale-and-slide reveal
- Timezone and message type (Plain Text / Rich Embed) shown on alarm cards
- Stagger entrance now fires on initial page load too (was only running on
  HTMX refreshes)
- Expanded timezone picker from ~68 curated zones to the full IANA set (~600)
- Screenshots converted to WebP and moved to `app/static/screenshots/`
- DeSynkro logo added to README credits

### Changed
- Cards are now semi-transparent for the glass effect
- Softer corners and tighter spacing between cards
- Header gradient shifted to a deep blue-to-sky palette
- Shimmer animation uses `transform` instead of `left` for better performance
- Added `pointer-events: none` to header shimmer pseudo-element
- Added `@media (prefers-reduced-motion: reduce)` fallback to disable
  decorative animations
- CSS cache-bust bumped to `v1.4`

### Fixed
- Character counter and markdown preview stopped working after submitting a
  form. OOB swap was replacing the modal container with a fresh element,
  destroying the event listeners. Changed to `innerHTML` swap to preserve
  listeners.
- Stagger entrance animation replayed on every 60-second auto-refresh, causing
  cards to briefly vanish. Now only runs once per page load.
- `toggleEmbed()` would throw if called when embed fields weren't in the DOM
- Initial char count always showed "0 / 2000" in edit forms; now renders the
  actual message length
- Toast created by `showToast()` was dismissed twice (by timer and
  MutationObserver). `data-tid` is now set before appending.
- User-supplied names now HTML-escaped in alarm cards, webhook chips, and
  dropdown options
- Editing an alarm with embed mode showed "None" in the title field if it
  had never been filled in

## 1.3

### Added
- Favicon set in `app/static/favicon/` (favicon.ico, PNG variants, apple-touch-icon)
- Export button, downloads all webhooks + alarms as a single JSON backup file
- Import modal, upload a JSON backup file with merge or replace mode
- Import validates every webhook/alarm through Pydantic schemas, skips invalid
  items; merge mode skips duplicate webhook names and alarm IDs
- Both lists auto-refresh after import via `HX-Trigger: refresh-lists`
- Toolbar in header with Export/Import buttons
- Webhook edit: pencil icon on each chip, modal form, rename propagates to all
  alarm references
- "Delete all" links at the bottom of each section, guarded by `hx-confirm`,
  returning count toasts
- DELETE `/webhooks` bulk endpoint (marks alarms as "(deleted)", refreshes
  both lists) and DELETE `/alarms` bulk endpoint
- Footer with `BUILT WITH ♥ BY DESYNKRO`, heartbeat animation on the heart
- Header logo: favicon replaces unicode emoji next to title (28px)
- Sticky footer pinned to bottom of viewport via flexbox column layout
- `X-Toast-Type` header on all error responses for consistent toast styling
- Dedup guard in `showToast()` prevents duplicate toasts within 2 seconds
- `<noscript>` banner at the top of the page, visible only when JavaScript
  is disabled, explaining that the app requires JS

### Changed
- Webhook form moved from inline `.hidden` toggle to modal overlay, matching
  the alarm pattern consistently
- Webhook GET routes (`/webhooks/new`, `/webhooks/{name}/edit`) serve modal
  forms; PUT `/webhooks/{name}` saves edits
- Renaming a webhook via edit updates all alarm `webhook_name` references in
  storage
- Error responses for `create_alarm`, `update_alarm`, `create_webhook`,
  `update_webhook`, `delete_webhook`, `delete_alarm` now return proper HTTP
  status codes with `X-Toast-Message` and `X-Toast-Type` headers (no more OOB
  error HTML fragments)
- Test message includes webhook name: `"Test message from {name} via Discord
  Notification Scheduler :wave:"`
- Test failure now returns the existing alarm card HTML instead of empty string
  (card no longer disappears from page)
- Delete webhook returns `HX-Trigger: refresh-lists` so alarm cards immediately
  show "(deleted)" for affected webhooks
- All webhook and alarm create/update operations return `X-Toast-Message`
  success toasts and OOB modal close swap
- Alarm list trigger expanded from `every 60s` to `every 60s, refresh-lists
  from:body` so it refreshes on import and webhook delete
- CSS cache-bust bumped to `v1.3`
- Self-hosted HTMX (`app/static/htmx.min.js`) so no external JavaScript
  requests are made on page load
- Self-hosted Inter variable font (7 woff2 unicode-range subsets in
  `app/static/fonts/`), removing the Google Fonts dependency entirely

### Fixed
- Zero external CDN requests on page load; a previous oversight left HTMX and
  Inter loading from third-party servers (unpkg and Google Fonts). Both are now
  self-hosted to fully align with the project's privacy commitment. No data
  leaves your network beyond the webhook POST to Discord. Apologies for the
  oversight.
- Removed unused `import os` from `storage.py`
- Removed unused `from datetime import datetime` from `models.py`
- Removed redundant `from datetime import datetime` inside `_alarm_card_html`
- Timezone `<option>` elements in alarm form now have proper `</option>` close
  tags
- Removed dead `.wh-form-area` CSS selectors for the old inline webhook form
  (converted to modal in this release)

## 1.2

### Added
- Live character counter (`0 / 2000`) under the message textarea in alarm
  forms
- Alarm list auto-refreshes every 60 seconds - scheduled fire badges appear
  without a manual page reload

### Changed
- Test button now updates `last_fired` timestamp and swaps the alarm card in
  place - Sent badge appears immediately
- Test endpoints return `X-Toast-Message`/`X-Toast-Type` response headers
  instead of OOB HTML fragments
- Toasts shown via `htmx:afterRequest` handler, no longer dependent on
  MutationObserver timing

## 1.1

### Added
- Live markdown preview now supports full Discord formatting:
  `#`/`##`/`###` headers, `> ` blockquotes, `- ` unordered lists,
  `1. ` ordered lists, `---` horizontal rules, `||spoiler||`
- Preview CSS for all new elements (headers, blockquotes, lists, spoilers, hr)

### Changed
- Markdown preview JS refactored from event delegation via `document` to
  direct listener on `#modal-area`, eliminating the fragile `closest('form')`
  / `querySelector` chain

### Fixed
- Toasts never auto-dismissing. Added `showToast()` and `dismissAfter()`
  functions that create toasts client-side and use `setTimeout` to fade
  and remove them after 4 seconds.
- Webhook form inputs appearing different widths when webhooks exist.
  The form is now pre-rendered in the page template (always at full width)
  instead of being loaded dynamically via HTMX. Toggle visibility with
  `.hidden` class.
- Form not hiding after successful save. Replaced `hx-on:after-success`
  with the correct HTMX v2 syntax `hx-on:after-request` checking
  `event.detail.successful`.
- Removed `/webhooks/new` endpoint (form is now part of the main template).
- Sealed `data/*.json` in `.gitignore` to prevent accidental secret leaks.
  JSON files are no longer tracked in git; the app auto-creates them if
  missing.
- Webhook names with special characters (`!`, `@`, etc.) breaking CSS
  selectors. Introduced `_safe_id()` helper to sanitize HTML id attributes.
- Markdown preview not working for dynamically loaded alarm forms.
  Replaced delegated `document` listener with direct listener on
  `#modal-area`.

## 1.0

- Initial release
