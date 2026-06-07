# App Simplification & AUTO RUN Design

**Date:** 2026-06-07  
**Status:** Approved

## Goal

Reduce UI surface area, remove redundant controls, and introduce a single AUTO RUN button that fully automates the maintenance pipeline. The app should be as minimal and automated as possible.

---

## 1. Navigation

**New sidebar order:**
1. Dashboard
2. Browse (moved from #5)
3. Downloads
4. Duplicates
5. Metadata
6. Settings

**Removed:** Search page — component, route, and nav link deleted entirely.

---

## 2. Dashboard

### Removed
- Full Scan button
- Top-up Scan button + threshold input field

### Kept (existing)
- Metrics grid (all stat cards)
- Overall progress bar
- Download Now button
- Komga Quick Scan All button
- Specific Scan (text input + submit)
- Enqueue Missing button
- Reset Missing button
- Library Scan button

### Added (new quick-action buttons)
- Full Library Organize
- Run System Flush
- Retry Failed

### New: AUTO RUN Button
- Large, full-width, hero-styled button
- Disabled while any auto-run stage is active
- Triggers `POST /api/system/auto-run`

**AUTO RUN stages (executed in order, server-side):**
1. System Flush
2. Scan Local Duplicates (with `ignore_chapter_ranges=True`)
3. Full Library Organize
4. Discover Unmatched
5. Sync Metadata

**AUTO RUN progress UI:**
- Displayed below the AUTO RUN button when running
- One row per stage: stage name, status icon (pending/running/done/error), progress bar, percentage
- Overall progress: `N/5 stages complete`
- Stop button — aborts current stage and clears the remaining chain
- Frontend polls `GET /api/system/auto-run/status` every 2s while running

### New: Komga Running Jobs Section
- Polls `GET /api/komga/tasks` every 5s
- Shows each running task: name + progress % (if Komga provides it)
- Hidden when no tasks are running
- Komga tasks come from Komga's own task/job API, proxied through the backend

---

## 3. Downloads

- Books with status `done` are never shown in the list
- The `done` filter chip is removed
- All other behavior unchanged (queued, downloading, failed, paused)

---

## 4. Browse

- Genre filter chips use `flex-wrap: wrap` — they reflow across multiple lines instead of a single long row
- Nav position moved to #2 (covered in Section 1)
- Everything else unchanged

---

## 5. Duplicates

No changes.

---

## 6. Metadata

No changes.

---

## 7. Settings

### Removed cards
- Retry Failed
- Reorganize by Chapters (Library Reorganize)
- Fix Komga Libraries (Komga Cleanup)
- Deduplicate Books
- Full Library Organize
- Run System Flush

### Kept
- Settings form only: concurrency, engine, auto-scan interval, Komga settings

---

## 8. New Backend Endpoints

### `POST /api/system/auto-run`
Starts the 5-stage auto-run chain. Returns `{"status": "started"}`.  
Rejects with 409 if already running.

### `GET /api/system/auto-run/status`
Returns current state of the auto-run chain:
```json
{
  "status": "running | idle | done | error",
  "current_stage": 2,
  "stages": [
    {"name": "System Flush", "status": "done", "progress": 100},
    {"name": "Scan Local Duplicates", "status": "running", "progress": 45},
    {"name": "Full Library Organize", "status": "pending", "progress": 0},
    {"name": "Discover Unmatched", "status": "pending", "progress": 0},
    {"name": "Sync Metadata", "status": "pending", "progress": 0}
  ]
}
```

### `POST /api/system/auto-run/stop`
Signals the chain to stop after the current stage completes (or immediately if the stage supports cancellation).

### `GET /api/komga/tasks`
Proxies Komga's task/job API. Returns:
```json
[
  {"name": "Scan library: Manga", "progress": 72},
  {"name": "Refresh metadata", "progress": null}
]
```
Progress is `null` if Komga doesn't provide it for that task type.

---

## 9. Implementation Notes

- The `ignore_chapter_ranges` flag for the deduplicate step: verify it exists in `POST /api/library/deduplicate`; add it if missing.
- AUTO RUN orchestration runs in a background thread, same pattern as system flush.
- Each stage delegates to the existing logic (flush, deduplicate, full-organize, discover, sync) — no duplication of business logic.
- Komga task proxying uses the existing `KomgaClient`. Check Komga API for `/api/v1/tasks` or `/api/v1/jobs` endpoints.
- Per-stage progress for stages 1, 3, 4, 5 comes from their existing status endpoints. Stage 2 (deduplicate) uses `GET /api/library/deduplicate/status`.
