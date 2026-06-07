# App Simplification & AUTO RUN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the UI by removing redundant controls, wiring up an AUTO RUN orchestrator (5-stage server-side pipeline), and adding a Komga running-jobs section to the dashboard.

**Architecture:** New `AutoRunner` class in `flush.py` (mirrors `SystemFlusher`/`LibraryOrganizer` pattern). Three new backend routes (`/api/system/auto-run`, status, stop) + one new Komga proxy route. Frontend changes remove cards/pages and add dashboard components that poll the new endpoints.

**Tech Stack:** FastAPI (Python), React + TypeScript + Vite, SQLite, Komga REST API.

---

## File Map

| File | Change |
|------|--------|
| `backend/app/library_organizer.py` | Add `ignore_chapter_ranges` param to `deduplicate_library` |
| `backend/app/komga.py` | Add `get_tasks()` method |
| `backend/app/flush.py` | Add `AutoRunner` class |
| `backend/app/main.py` | Wire `_auto_runner`, 4 new routes, `autoRunRunning` in summary |
| `frontend/src/api.ts` | Add `AutoRunStage`, `AutoRunStatus`, `KomgaTask` types + 4 methods; add `autoRunRunning` to `Summary` |
| `frontend/src/App.tsx` | Remove Search, reorder nav, add `autoRunRunning` to `emptySummary` |
| `frontend/src/pages/SettingsPage.tsx` | Remove 6 cards/buttons, keep only settings form + system info |
| `frontend/src/pages/DownloadsPage.tsx` | Filter out done books permanently; remove `done` chip |
| `frontend/src/styles.css` | Fix `.browse-genre-strip` to flex-wrap |
| `frontend/src/pages/DashboardPage.tsx` | Remove Full Scan/Top-up; add quick actions, `AutoRunCard`, `KomgaTasksSection` |

---

## Task 1: `ignore_chapter_ranges` flag in `deduplicate_library`

**Files:**
- Modify: `backend/app/library_organizer.py:407-414`

- [ ] **Step 1: Add `ignore_chapter_ranges` parameter**

In `library_organizer.py`, find `def deduplicate_library(` and add the parameter:

```python
def deduplicate_library(
    conn: sqlite3.Connection,
    library_root: Path,
    komga_client,
    stop_event: threading.Event | None = None,
    threshold: float = 0.82,
    progress: dict | None = None,
    ignore_chapter_ranges: bool = False,
) -> dict:
```

- [ ] **Step 2: Add skip logic for cross-range groups**

After the `group = [books[i] for i in group_indices]` line (around line 501), add:

```python
        # When called from auto-run, skip groups where every member is in a
        # different chapter-range parent folder — those are legitimately
        # separate range placements, not duplicates.
        if ignore_chapter_ranges:
            parent_names = [b["folder"].parent.name for b in group]
            if (
                all(p in RANGE_NAMES for p in parent_names)
                and len(set(parent_names)) == len(parent_names)
            ):
                continue
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/library_organizer.py
git commit -m "feat: add ignore_chapter_ranges flag to deduplicate_library"
```

---

## Task 2: Komga `get_tasks()` method

**Files:**
- Modify: `backend/app/komga.py`

- [ ] **Step 1: Add `get_tasks` to `KomgaClient`**

Add this method to `KomgaClient` (after `quick_scan_library` around line 75):

```python
    def get_tasks(self) -> list[dict]:
        """Return active Komga background tasks proxied for the frontend."""
        try:
            resp = self.session.get(f"{self.settings.url}/api/v1/tasks", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            tasks = data if isinstance(data, list) else data.get("content", [])
            return [
                {
                    "name": t.get("type") or t.get("name") or "Task",
                    "progress": t.get("progress"),
                }
                for t in tasks
            ]
        except Exception:
            return []
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/komga.py
git commit -m "feat: add get_tasks() to KomgaClient for Komga job proxying"
```

---

## Task 3: `AutoRunner` class in `flush.py`

**Files:**
- Modify: `backend/app/flush.py`

- [ ] **Step 1: Add `_AUTO_RUN_STAGES` and the `AutoRunner` class**

Append to `backend/app/flush.py` (after the `SystemFlusher` class):

```python
# ── Auto Runner ────────────────────────────────────────────────────────────────

_AUTO_RUN_STAGES = [
    ("flush",    "System Flush"),
    ("dedup",    "Scan Local Duplicates"),
    ("organize", "Full Library Organize"),
    ("discover", "Discover Unmatched"),
    ("sync",     "Sync Metadata"),
]


class AutoRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stages: list[dict] = self._fresh_stages()
        self._stop_requested = False
        self._dedup_progress: dict = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _fresh_stages(self) -> list[dict]:
        return [
            {"id": sid, "name": name, "status": "pending", "progress": 0}
            for sid, name in _AUTO_RUN_STAGES
        ]

    def start(
        self,
        *,
        flusher,
        organizer,
        conn: sqlite3.Connection,
        settings,
        komga_client,
        download_queue,
        asura_client,
        scan_scheduler,
        scan_stop_event,
    ) -> bool:
        with self._lock:
            if self.running:
                return False
            self._stop_requested = False
            self._stages = self._fresh_stages()
            self._dedup_progress = {}
            self._thread = threading.Thread(
                target=self._run,
                kwargs=dict(
                    flusher=flusher,
                    organizer=organizer,
                    conn=conn,
                    settings=settings,
                    komga_client=komga_client,
                    download_queue=download_queue,
                    asura_client=asura_client,
                    scan_scheduler=scan_scheduler,
                    scan_stop_event=scan_stop_event,
                ),
                name="auto-runner",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop_requested = True

    def status(self) -> dict:
        stages = []
        for s in self._stages:
            stage = dict(s)
            # Overlay live dedup progress when that stage is actively running
            if stage["id"] == "dedup" and stage["status"] == "running":
                total = self._dedup_progress.get("total", 0)
                processed = self._dedup_progress.get("processed", 0)
                if total:
                    stage["progress"] = round(processed / total * 100)
            stages.append(stage)

        if self.running:
            overall = "running"
        elif any(s["status"] == "error" for s in stages):
            overall = "error"
        elif any(s["status"] in ("done", "cancelled") for s in stages):
            overall = "done"
        else:
            overall = "idle"

        current = next(
            (i + 1 for i, s in enumerate(stages) if s["status"] == "running"), 0
        )
        return {"status": overall, "current_stage": current, "stages": stages}

    def _set(self, stage_id: str, status: str, progress: int = 0) -> None:
        for s in self._stages:
            if s["id"] == stage_id:
                s["status"] = status
                s["progress"] = progress

    def _update_progress(self, stage_id: str, progress: int) -> None:
        for s in self._stages:
            if s["id"] == stage_id:
                s["progress"] = progress

    def _cancel_remaining(self) -> None:
        for s in self._stages:
            if s["status"] == "pending":
                s["status"] = "cancelled"
                s["progress"] = 0

    def _run(
        self,
        *,
        flusher,
        organizer,
        conn: sqlite3.Connection,
        settings,
        komga_client,
        download_queue,
        asura_client,
        scan_scheduler,
        scan_stop_event,
    ) -> None:
        import time
        from .library_organizer import deduplicate_library
        from .metadata_discovery import discover_unmatched_local_metadata
        from .metadata_sync import sync_manga_metadata_to_komga

        # ── Stage 1: System Flush ─────────────────────────────────────────────
        self._set("flush", "running", 0)
        flusher.start(
            conn=conn,
            settings=settings,
            download_queue=download_queue,
            komga_client=komga_client,
            asura_client=asura_client,
            scan_scheduler=scan_scheduler,
            scan_stop_event=scan_stop_event,
        )
        while flusher.running and not self._stop_requested:
            s = flusher.status()
            tasks = s.get("tasks", [])
            done = sum(1 for t in tasks if t["status"] in ("done", "error", "cancelled"))
            total = len(tasks)
            self._update_progress("flush", round(done / total * 100) if total else 0)
            time.sleep(1)
        if self._stop_requested:
            flusher.stop()
            self._set("flush", "cancelled", 0)
            return self._cancel_remaining()
        flush_tasks = flusher.status().get("tasks", [])
        has_error = any(t["status"] == "error" for t in flush_tasks)
        self._set("flush", "error" if has_error else "done", 0 if has_error else 100)

        if self._stop_requested:
            return self._cancel_remaining()

        # ── Stage 2: Scan Local Duplicates (ignore chapter ranges) ────────────
        self._set("dedup", "running", 0)
        self._dedup_progress.clear()
        try:
            deduplicate_library(
                conn,
                settings.library_root,
                komga_client,
                stop_event=None,
                progress=self._dedup_progress,
                ignore_chapter_ranges=True,
            )
            self._set("dedup", "done", 100)
        except Exception as exc:
            self._set("dedup", "error", 0)
            repository.log(conn, "error", f"Auto-run dedup failed: {exc}")

        if self._stop_requested:
            return self._cancel_remaining()

        # ── Stage 3: Full Library Organize ────────────────────────────────────
        self._set("organize", "running", 0)
        organizer.start(conn=conn, settings=settings, komga_client=komga_client)
        while organizer.running and not self._stop_requested:
            s = organizer.status()
            tasks = s.get("tasks", [])
            done = sum(1 for t in tasks if t["status"] in ("done", "error", "cancelled"))
            total = len(tasks)
            self._update_progress("organize", round(done / total * 100) if total else 0)
            time.sleep(1)
        if self._stop_requested:
            organizer.stop()
            self._set("organize", "cancelled", 0)
            return self._cancel_remaining()
        org_tasks = organizer.status().get("tasks", [])
        has_error = any(t["status"] == "error" for t in org_tasks)
        self._set("organize", "error" if has_error else "done", 0 if has_error else 100)

        if self._stop_requested:
            return self._cancel_remaining()

        # ── Stage 4: Discover Unmatched ───────────────────────────────────────
        self._set("discover", "running", 0)
        try:
            discover_unmatched_local_metadata(conn, asura_client)
            self._set("discover", "done", 100)
        except Exception as exc:
            self._set("discover", "error", 0)
            repository.log(conn, "error", f"Auto-run discover failed: {exc}")

        if self._stop_requested:
            return self._cancel_remaining()

        # ── Stage 5: Sync Metadata ────────────────────────────────────────────
        self._set("sync", "running", 0)
        if not komga_client.enabled:
            self._set("sync", "done", 100)
        else:
            try:
                candidates = repository.metadata_sync_candidates(conn)
                total = len(candidates)
                synced = 0
                for c in candidates:
                    if self._stop_requested:
                        break
                    try:
                        sync_manga_metadata_to_komga(conn, komga_client, int(c["id"]))
                        synced += 1
                    except Exception:
                        pass
                    self._update_progress("sync", round(synced / total * 100) if total else 100)
                if self._stop_requested:
                    self._set("sync", "cancelled", round(synced / total * 100) if total else 0)
                    return self._cancel_remaining()
                self._set("sync", "done", 100)
            except Exception as exc:
                self._set("sync", "error", 0)
                repository.log(conn, "error", f"Auto-run sync failed: {exc}")

        repository.log(conn, "info", "Auto-run complete")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/flush.py
git commit -m "feat: add AutoRunner orchestrator to flush.py"
```

---

## Task 4: Wire AutoRunner into `main.py`

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Import and instantiate `AutoRunner`**

Find the line:
```python
from .flush import SystemFlusher, LibraryOrganizer  # noqa: E402  (after module-level vars are defined)
_flusher = SystemFlusher()
_organizer = LibraryOrganizer()
```

Replace with:
```python
from .flush import SystemFlusher, LibraryOrganizer, AutoRunner  # noqa: E402
_flusher = SystemFlusher()
_organizer = LibraryOrganizer()
_auto_runner = AutoRunner()
```

- [ ] **Step 2: Add `autoRunRunning` to the summary endpoint**

Find `data["fullOrganizeRunning"] = _organizer.running` in the `summary()` function and add the line after it:

```python
    data["autoRunRunning"] = _auto_runner.running
```

- [ ] **Step 3: Add auto-run routes** (add after the `system/flush/status` route, around line 932)

```python
@app.post("/api/system/auto-run")
def start_auto_run(_user: dict = Depends(authenticated_user)) -> dict:
    started = _auto_runner.start(
        flusher=_flusher,
        organizer=_organizer,
        conn=conn,
        settings=settings,
        komga_client=komga_client,
        download_queue=download_queue,
        asura_client=asura_client,
        scan_scheduler=scan_scheduler,
        scan_stop_event=scan_stop_event,
    )
    if not started:
        raise HTTPException(status_code=409, detail="Auto-run already running")
    repository.log(conn, "info", "Auto-run started")
    return {"started": True}


@app.post("/api/system/auto-run/stop")
def stop_auto_run(_user: dict = Depends(authenticated_user)) -> dict:
    _auto_runner.stop()
    repository.log(conn, "info", "Auto-run stop requested")
    return {"stopped": True}


@app.get("/api/system/auto-run/status")
def auto_run_status(_user: dict = Depends(authenticated_user)) -> dict:
    return _auto_runner.status()
```

- [ ] **Step 4: Add Komga tasks proxy route**

```python
@app.get("/api/komga/tasks")
def komga_tasks(_user: dict = Depends(authenticated_user)) -> list:
    return komga_client.get_tasks() if komga_client.enabled else []
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: add auto-run and komga-tasks routes to main.py"
```

---

## Task 5: Frontend — `api.ts` new types and methods

**Files:**
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: Add `autoRunRunning` to `Summary` type** (around line 19)

Find `fullOrganizeRunning: boolean;` and add after it:
```typescript
  autoRunRunning: boolean;
```

- [ ] **Step 2: Add new types** (after `FullOrganizeStatus` type, around line 258)

```typescript
export type AutoRunStage = {
  id: string;
  name: string;
  status: "pending" | "running" | "done" | "error" | "cancelled";
  progress: number;
};

export type AutoRunStatus = {
  status: "idle" | "running" | "done" | "error";
  current_stage: number;
  stages: AutoRunStage[];
};

export type KomgaTask = {
  name: string;
  progress: number | null;
};
```

- [ ] **Step 3: Add new API methods** (at the end of the `api` object, before the closing `}`)

```typescript
  autoRunStart: () => request<{ started: boolean }>("/api/system/auto-run", { method: "POST" }),
  autoRunStop: () => request<{ stopped: boolean }>("/api/system/auto-run/stop", { method: "POST" }),
  autoRunStatus: () => request<AutoRunStatus>("/api/system/auto-run/status"),
  komgaTasks: () => request<KomgaTask[]>("/api/komga/tasks"),
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: add AutoRunStatus, KomgaTask types and api methods"
```

---

## Task 6: `App.tsx` — nav cleanup

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Remove Search from `Tab` type and `VALID_TABS`**

Find:
```typescript
type Tab = "dashboard" | "downloads" | "duplicates" | "metadata" | "browse" | "search" | "settings";

const VALID_TABS: Tab[] = ["dashboard", "downloads", "duplicates", "metadata", "browse", "search", "settings"];
```

Replace with:
```typescript
type Tab = "dashboard" | "browse" | "downloads" | "duplicates" | "metadata" | "settings";

const VALID_TABS: Tab[] = ["dashboard", "browse", "downloads", "duplicates", "metadata", "settings"];
```

- [ ] **Step 2: Add `autoRunRunning: false` to `emptySummary`**

Find `fullOrganizeRunning: false,` and add after it:
```typescript
  autoRunRunning: false,
```

- [ ] **Step 3: Reorder tabs array and remove Search**

Find the `tabs` array and replace it with:
```typescript
  const tabs: Array<{ id: Tab; label: string; icon: React.ReactElement; badge?: number }> = [
    { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={15} /> },
    { id: "browse",    label: "Browse",    icon: <Library size={15} /> },
    { id: "downloads", label: "Downloads", icon: <Download size={15} />, badge: activeDownloads || undefined },
    { id: "duplicates", label: "Duplicates", icon: <CopyX size={15} /> },
    { id: "metadata",  label: "Metadata",  icon: <Tags size={15} /> },
    { id: "settings",  label: "Settings",  icon: <Settings size={15} /> },
  ];
```

- [ ] **Step 4: Remove SearchPage render and import**

Find `{activeTab === "search" && (` block and delete it (4 lines).

Remove `import { SearchPage } from "./pages/SearchPage";` from imports.

Remove `Search,` from the lucide-react import.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: remove Search page, reorder nav (Browse to #2)"
```

---

## Task 7: `SettingsPage.tsx` — strip cards

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Remove component definitions no longer needed**

Delete the entire `FlushCard` function (lines ~39–160), `ReorgProgress` function (~173–199), `DedupProgress` function (~201–230), and `FullOrganizeCard` function (~232–364).

Also delete `TaskIcon` (~7–13) and `TaskBar` (~15–37) and `ProgressBar` (~162–171) helper components.

- [ ] **Step 2: Strip unused imports**

Replace the import line:
```typescript
import { FormEvent, useEffect, useState } from "react";
import { FolderSync, GitMerge, Layers, Wrench, Square, Zap, CheckCircle2, XCircle, Loader, Clock, Ban } from "lucide-react";
import { api, FlushTask, FullOrganizeStatus } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";
```

With:
```typescript
import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";
```

- [ ] **Step 3: Rewrite `SettingsPage` export**

Replace the entire `export function SettingsPage(...)` with the slimmed-down version that keeps only the settings form and system info:

```typescript
export function SettingsPage({ summary, loading, runAction }: SharedProps) {
  const [intervalDays,         setIntervalDays]         = useState(summary.autoScanEveryDays);
  const [downloadConcurrency,  setDownloadConcurrency]  = useState(summary.downloadConcurrency);
  const [browserConcurrency,   setBrowserConcurrency]   = useState(summary.browserConcurrency);
  const [imageDownloadWorkers, setImageDownloadWorkers] = useState(summary.imageDownloadWorkers);
  const [readerEngine,         setReaderEngine]         = useState<"playwright" | "selenium">(summary.readerEngine);
  const [komgaAutoEnabled,     setKomgaAutoEnabled]     = useState(summary.komgaAutoEnabled);
  const [reorganizeOnDrain,    setReorganizeOnDrain]    = useState(summary.reorganizeOnDrain);

  useEffect(() => {
    setIntervalDays(summary.autoScanEveryDays);
    setDownloadConcurrency(summary.downloadConcurrency);
    setBrowserConcurrency(summary.browserConcurrency);
    setImageDownloadWorkers(summary.imageDownloadWorkers);
    setReaderEngine(summary.readerEngine);
    setKomgaAutoEnabled(summary.komgaAutoEnabled);
    setReorganizeOnDrain(summary.reorganizeOnDrain);
  }, [
    summary.autoScanEveryDays, summary.downloadConcurrency, summary.browserConcurrency,
    summary.imageDownloadWorkers, summary.readerEngine, summary.komgaAutoEnabled, summary.reorganizeOnDrain,
  ]);

  async function submitSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction("Save settings", () =>
      api.updateSettings(
        intervalDays, downloadConcurrency, browserConcurrency,
        imageDownloadWorkers, readerEngine, komgaAutoEnabled, reorganizeOnDrain,
      ),
    );
  }

  return (
    <>
      <div className="page-header">
        <div className="page-title-row"><h2>Settings</h2></div>
      </div>

      <div className="settings-grid">
        <div className="card">
          <div className="card-title">Configuration</div>
          <form className="settings-fields" onSubmit={submitSettings}>
            <div className="field-row">
              <label htmlFor="interval">Auto scan every</label>
              <input id="interval" type="number" min={0} value={intervalDays}
                onChange={(e) => setIntervalDays(Number(e.target.value))} />
              <span style={{ color: "var(--text-3)", fontSize: 13 }}>days</span>
              <span className="field-help" style={{ flexBasis: "100%" }}>0 disables auto-scheduling. Enabled scans run at 2:00 AM.</span>
            </div>
            <div className="field-row">
              <label htmlFor="dlc">Concurrent downloads</label>
              <input id="dlc" type="number" min={1} max={6} value={downloadConcurrency}
                onChange={(e) => setDownloadConcurrency(Number(e.target.value))} />
            </div>
            <div className="field-row">
              <label htmlFor="brc" title="Limit simultaneous rendered reader pages.">Browser pages</label>
              <input id="brc" type="number" min={1} max={4} value={browserConcurrency}
                onChange={(e) => setBrowserConcurrency(Number(e.target.value))} />
              <span className="field-help" style={{ flexBasis: "100%" }}>Controls CPU-heavy reader rendering</span>
            </div>
            <div className="field-row">
              <label htmlFor="img" title="Limit parallel HTTP image downloads per chapter.">Image workers</label>
              <input id="img" type="number" min={1} max={8} value={imageDownloadWorkers}
                onChange={(e) => setImageDownloadWorkers(Number(e.target.value))} />
              <span className="field-help" style={{ flexBasis: "100%" }}>Controls HTTP transfer parallelism</span>
            </div>
            <div className="field-row">
              <label htmlFor="eng">Reader engine</label>
              <select id="eng" value={readerEngine}
                onChange={(e) => setReaderEngine(e.target.value as "playwright" | "selenium")}
                style={{ width: "auto" }}>
                <option value="playwright">Playwright</option>
                <option value="selenium">Selenium</option>
              </select>
            </div>
            <div className="field-row">
              <input id="komga-auto" type="checkbox" checked={komgaAutoEnabled}
                onChange={(e) => setKomgaAutoEnabled(e.target.checked)} />
              <label htmlFor="komga-auto">Auto Komga import/scan after downloads</label>
              <span className="field-help" style={{ flexBasis: "100%" }}>
                Imports after the queue finishes, then waits 1 hour before a fast scan.
              </span>
            </div>
            <div className="field-row">
              <input id="reorg-drain" type="checkbox" checked={reorganizeOnDrain}
                onChange={(e) => setReorganizeOnDrain(e.target.checked)} />
              <label htmlFor="reorg-drain">Auto reorganize by chapter count after downloads</label>
              <span className="field-help" style={{ flexBasis: "100%" }}>
                Moves each book into the correct range library after the queue drains.
              </span>
            </div>
            <button className="btn-primary" style={{ width: "fit-content", height: 38 }} disabled={loading}>
              Save settings
            </button>
          </form>
        </div>

        <div className="card">
          <div className="card-title">System Info</div>
          <div className="sys-grid">
            <StatCard label="Library root" value={summary.libraryRoot || "Not configured"} />
            <StatCard label="Komga URL"    value={summary.komgaUrl || "Not configured"} />
            <StatCard label="Last scan"    value={summary.lastScanAt ? new Date(summary.lastScanAt).toLocaleString() : "Never"} />
            <StatCard label="Scan status"  value={summary.scanRunning ? "Running" : summary.limitedScanActive ? "Top-up active" : "Idle"} />
          </div>
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: simplify SettingsPage — keep only settings form and system info"
```

---

## Task 8: `DownloadsPage.tsx` — hide finished books

**Files:**
- Modify: `frontend/src/pages/DownloadsPage.tsx`

- [ ] **Step 1: Remove `done` from `FilterType`**

Find:
```typescript
type FilterType = "all" | "downloading" | "queued" | "done";
```

Replace with:
```typescript
type FilterType = "all" | "downloading" | "queued";
```

- [ ] **Step 2: Always filter out done books and remove `done` chip**

Find the `filtered` constant:
```typescript
  const filtered = progress.filter((p) => {
    if (search && !p.manga_title.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "downloading" && p.running === 0) return false;
    if (filter === "queued"     && p.queued === 0)   return false;
    if (filter === "done"       && (p.queued > 0 || p.running > 0 || p.missing_count > 0)) return false;
    return true;
  });
```

Replace with:
```typescript
  const filtered = progress.filter((p) => {
    // Always hide books with no active work
    if (p.running === 0 && p.queued === 0 && p.paused === 0 && p.failed === 0) return false;
    if (search && !p.manga_title.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "downloading" && p.running === 0) return false;
    if (filter === "queued"      && p.queued === 0)  return false;
    return true;
  });
```

- [ ] **Step 3: Remove `done` from the filter chips render**

Find:
```typescript
          {(["all", "downloading", "queued", "done"] as FilterType[]).map((f) => (
```

Replace with:
```typescript
          {(["all", "downloading", "queued"] as FilterType[]).map((f) => (
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/DownloadsPage.tsx
git commit -m "feat: hide completed downloads from Downloads page"
```

---

## Task 9: `styles.css` — genre flex-wrap

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Update `.browse-genre-strip`**

Find:
```css
.browse-genre-strip {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  max-width: 100%;
  padding: 2px 0 12px;
  margin-bottom: 2px;
}

.browse-genre-strip .chip { flex: 0 0 auto; }
```

Replace with:
```css
.browse-genre-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 100%;
  padding: 2px 0 12px;
  margin-bottom: 2px;
}

.browse-genre-strip .chip { flex: 0 0 auto; }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/styles.css
git commit -m "feat: make genre filter chips flex-wrap in Browse page"
```

---

## Task 10: `DashboardPage.tsx` — overhaul

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx`

- [ ] **Step 1: Update imports**

Replace the current import block with:

```typescript
import { FormEvent, useEffect, useRef, useState } from "react";
import {
  Activity,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  Clock,
  Download,
  HardDrive,
  Layers,
  Loader,
  Pause,
  Play,
  RefreshCw,
  Search,
  Server,
  Square,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { api, AutoRunStage, AutoRunStatus, DebugThreads, KomgaTask, LogEntry } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";
```

- [ ] **Step 2: Remove Top-up row and Full Scan button from Scan Controls**

Inside the `DashboardPage` function, delete the `scanLimit`, `scanLimitFocused` state and the `updateScanLimit` function. Also delete the `topup-row` JSX block and the Full Scan button from `scan-actions`.

Replace the Scan Controls card body (the `scan-actions` div and below up to the `status-bar`) with:

```tsx
        <div className="scan-actions">
          <button
            className="btn-ghost danger"
            onClick={() => runAction("Stop scan", api.stopScan)}
            disabled={loading || (!summary.scanRunning && !summary.limitedScanActive)}
            title="Stop the active scan after its current request finishes."
          >
            <X size={13} /> Stop scan
          </button>
          <button
            className="btn-ghost danger"
            onClick={() => runAction("Stop all scans", api.stopAllScans)}
            disabled={loading}
            title="Disable top-up, cancel every scan producer, and stop new scan enqueueing."
          >
            <X size={13} /> Stop all
          </button>
          <button
            className="btn-ghost"
            onClick={() => runAction("Library reindex", api.libraryScan)}
            disabled={loading}
            title="Re-read local folder and recount CBZ files."
          >
            Reindex
          </button>
          <button
            className="btn-ghost"
            onClick={confirmEnqueueMissing}
            disabled={loading || summary.missingChapters === 0}
          >
            Re-enqueue missing ({summary.missingChapters.toLocaleString()})
          </button>
          <button
            className="btn-ghost danger"
            onClick={confirmResetMissing}
            disabled={loading}
          >
            Reset missing
          </button>
          <button
            className="btn-ghost"
            onClick={confirmKomgaScanAll}
            disabled={loading}
          >
            Komga scan all
          </button>
          <button
            className="btn-ghost"
            onClick={() => runAction("Import all libraries", api.importAllBooks)}
            disabled={loading}
          >
            Import all
          </button>
          <button
            className="btn-ghost"
            onClick={() => runAction("Full library organize", api.fullOrganizeStart)}
            disabled={loading || summary.fullOrganizeRunning}
          >
            <Layers size={13} /> Full library organize
          </button>
          <button
            className="btn-ghost"
            onClick={() => runAction("System flush", api.systemFlush)}
            disabled={loading || summary.flushRunning}
          >
            <Zap size={13} /> System flush
          </button>
          <button
            className="btn-ghost"
            onClick={() => runAction("Retry failed downloads", api.retryFailedDownloads)}
            disabled={loading || summary.failedJobs === 0}
          >
            Retry failed ({summary.failedJobs})
          </button>
        </div>
```

- [ ] **Step 3: Add `AutoRunCard` component** (add before the closing `</>` of `DashboardPage` return, after the Thread panel section)

```tsx
      <AutoRunCard autoRunRunning={summary.autoRunRunning} loading={loading} />
      <KomgaTasksSection />
```

- [ ] **Step 4: Add `AutoRunCard` component definition** (add before the `fmtBytes` helper, after the `DashboardPage` function closing brace)

```tsx
/* ── Auto Run Card ────────────────────────────────────────────────── */
function StageIcon({ status }: { status: AutoRunStage["status"] }) {
  if (status === "running")   return <Loader size={15} style={{ animation: "spin 1s linear infinite" }} />;
  if (status === "done")      return <CheckCircle2 size={15} style={{ color: "var(--accent)" }} />;
  if (status === "error")     return <XCircle size={15} style={{ color: "var(--red, #ef4444)" }} />;
  if (status === "cancelled") return <X size={15} style={{ color: "var(--text-3)" }} />;
  return <Clock size={15} style={{ color: "var(--text-3)" }} />;
}

function AutoRunCard({ autoRunRunning, loading }: { autoRunRunning: boolean; loading: boolean }) {
  const [autoStatus, setAutoStatus] = useState<AutoRunStatus | null>(null);
  const [everStarted, setEverStarted] = useState(false);

  // Restore state on mount (page navigation doesn't lose progress)
  useEffect(() => {
    api.autoRunStatus().then((s) => {
      if (s.status !== "idle") {
        setAutoStatus(s);
        setEverStarted(true);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!autoRunRunning) return;
    setEverStarted(true);
    const iv = setInterval(async () => {
      try {
        const s = await api.autoRunStatus();
        setAutoStatus(s);
        if (s.status !== "running") clearInterval(iv);
      } catch {
        clearInterval(iv);
      }
    }, 2000);
    return () => clearInterval(iv);
  }, [autoRunRunning]);

  async function startAutoRun() {
    setEverStarted(true);
    setAutoStatus(null);
    try {
      await api.autoRunStart();
      const s = await api.autoRunStatus();
      setAutoStatus(s);
    } catch (e) {
      console.error(e);
    }
  }

  async function stopAutoRun() {
    await api.autoRunStop();
  }

  const stages = autoStatus?.stages ?? [];
  const doneCount = stages.filter((s) => s.status === "done").length;
  const hasError = stages.some((s) => s.status === "error");

  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Play size={16} style={{ color: "var(--accent)" }} />
        AUTO RUN
      </div>

      <p style={{ color: "var(--text-2)", marginBottom: 14, lineHeight: 1.5, fontSize: 13 }}>
        Runs the full maintenance pipeline: System Flush → Scan Local Duplicates → Full Library Organize → Discover Unmatched → Sync Metadata.
      </p>

      {everStarted && stages.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
          {/* Overall bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 2 }}>
            <div style={{ flex: 1, height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: `${(doneCount / stages.length) * 100}%`,
                background: hasError ? "var(--red, #ef4444)" : "var(--accent)",
                borderRadius: 3,
                transition: "width 0.4s ease",
              }} />
            </div>
            <span style={{ fontSize: 12, color: "var(--text-3)", whiteSpace: "nowrap" }}>
              {doneCount}/{stages.length} stages
            </span>
          </div>

          {stages.map((stage) => (
            <div key={stage.id}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StageIcon status={stage.status} />
                <span style={{ fontWeight: 500, flex: 1, fontSize: 13 }}>{stage.name}</span>
                {stage.status !== "pending" && (
                  <span style={{ fontSize: 12, color: "var(--text-3)", whiteSpace: "nowrap" }}>
                    {stage.progress}%
                  </span>
                )}
              </div>
              <div style={{ height: 3, background: "var(--border)", borderRadius: 2, marginTop: 4, overflow: "hidden" }}>
                <div style={{
                  height: "100%",
                  width: `${stage.progress}%`,
                  background:
                    stage.status === "error"     ? "var(--red, #ef4444)" :
                    stage.status === "cancelled" ? "var(--border)"       :
                    "var(--accent)",
                  borderRadius: 2,
                  transition: "width 0.4s ease",
                  animation: stage.status === "running" ? "pulse-bar 1.4s ease-in-out infinite" : undefined,
                }} />
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {autoRunRunning ? (
          <button
            className="btn-ghost btn-sm danger"
            onClick={stopAutoRun}
            disabled={loading}
          >
            <Square size={13} /> Stop auto-run
          </button>
        ) : (
          <button
            className="btn-primary"
            style={{ width: "100%", height: 48, fontSize: 16, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}
            onClick={startAutoRun}
            disabled={loading || autoRunRunning}
          >
            <Play size={18} /> AUTO RUN
          </button>
        )}
        {everStarted && !autoRunRunning && stages.length > 0 && (
          <span style={{ fontSize: 12, color: hasError ? "var(--red, #ef4444)" : "var(--accent)" }}>
            {hasError ? "Completed with errors" : autoStatus?.status === "done" ? "Completed" : ""}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Komga Tasks Section ──────────────────────────────────────────── */
function KomgaTasksSection() {
  const [tasks, setTasks] = useState<KomgaTask[]>([]);

  useEffect(() => {
    const poll = async () => {
      try {
        setTasks(await api.komgaTasks());
      } catch {
        setTasks([]);
      }
    };
    poll();
    const iv = setInterval(poll, 5000);
    return () => clearInterval(iv);
  }, []);

  if (tasks.length === 0) return null;

  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Activity size={14} /> Komga Running Jobs
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {tasks.map((task, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Loader size={13} style={{ animation: "spin 1s linear infinite", color: "var(--accent)", flexShrink: 0 }} />
            <span style={{ flex: 1, fontSize: 13 }}>{task.name}</span>
            {task.progress != null && (
              <>
                <span style={{ fontSize: 12, color: "var(--text-3)", whiteSpace: "nowrap" }}>{task.progress}%</span>
                <div style={{ width: 80, height: 4, background: "var(--border)", borderRadius: 2, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${task.progress}%`, background: "var(--accent)", borderRadius: 2 }} />
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/DashboardPage.tsx
git commit -m "feat: dashboard overhaul — add AUTO RUN card, Komga jobs section, new quick actions"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 9 spec sections covered: nav reorder, search removed, dashboard buttons, auto-run stages, komga jobs, downloads hide-done, browse genre wrap, settings stripped, new backend endpoints
- [x] **No placeholders:** All code is concrete — no TBD/TODO
- [x] **Type consistency:** `AutoRunStage`, `AutoRunStatus`, `KomgaTask` defined in Task 5 and used in Task 10; `autoRunRunning` added to `Summary` in Task 5 and `emptySummary` in Task 6
- [x] **Scope check:** All changes are in-scope; no new pages or major refactors beyond spec
- [x] **Ambiguity:** `ignore_chapter_ranges` semantics defined precisely (skip cross-range groups); "hide done" means filter by zero active work

---

## Post-implementation

After all tasks complete, manually verify:
1. AUTO RUN button triggers all 5 stages and shows per-stage % progress
2. Stage 1 (System Flush) progress bar fills as flush tasks complete
3. Downloads page shows no completed books
4. Browse genre chips wrap on narrow screens
5. Settings page shows only the form (no cards for flush, organize, dedup, etc.)
6. Search tab gone from nav; Browse is now 2nd
7. Komga tasks section appears when Komga has running jobs, disappears when idle
