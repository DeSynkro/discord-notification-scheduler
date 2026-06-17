# Changelog

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
