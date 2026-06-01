# Manga Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI + React app that scans Asura Scans, indexes a Komga library, and automatically downloads missing titles and chapters.

**Architecture:** The backend owns filesystem access, site scanning, SQLite state, download queueing, and scheduling. The frontend is a Vite React dashboard that calls the backend and renders library state, queue state, and controls.

**Tech Stack:** Python 3.13, FastAPI, SQLite, Selenium, requests, BeautifulSoup, Vite, React, TypeScript.

---

### Task 1: Project Scaffold

**Files:**

- Create: `requirements.txt`
- Create: `.env.example`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`

- [ ] Create backend and frontend skeletons.
- [ ] Add configurable `MANGA_LIBRARY_ROOT`, `APP_DATA_DIR`, and downloader concurrency settings.
- [ ] Add Vite scripts for frontend development and build.

### Task 2: Persistence Layer

**Files:**

- Create: `backend/app/database.py`
- Create: `backend/app/models.py`
- Create: `backend/app/repository.py`

- [ ] Initialize SQLite schema at startup.
- [ ] Store manga, chapters, local inventory, jobs, settings, and logs.
- [ ] Add repository functions used by scanners and API routes.

### Task 3: Asura Scanner

**Files:**

- Create: `backend/app/asura.py`

- [ ] Fetch browse pages with a browser-like user agent.
- [ ] Parse series cards and pagination links.
- [ ] Fetch series pages and parse chapter URLs and numbers.
- [ ] Support specific manga scan by URL or title.

### Task 4: Local Library Scanner

**Files:**

- Create: `backend/app/library.py`

- [ ] Walk the configured books root.
- [ ] Count `.cbz` files per folder.
- [ ] Extract chapter numbers from common filename patterns.
- [ ] Store inventory in SQLite.

### Task 5: Downloader Queue

**Files:**

- Create: `backend/app/downloader.py`
- Create: `backend/app/queue.py`

- [ ] Refactor Selenium reader-image extraction into reusable functions.
- [ ] Download image files into a temp folder.
- [ ] Build CBZ files in the target manga folder.
- [ ] Run one queue worker in the backend process.
- [ ] Retry jobs and expose status.

### Task 6: Scheduler and API

**Files:**

- Create: `backend/app/scheduler.py`
- Modify: `backend/app/main.py`

- [ ] Start background worker and scheduler on FastAPI startup.
- [ ] Add endpoints for summary, books, jobs, settings, full scan, specific scan, local library scan, queue pause, and queue resume.

### Task 7: React Dashboard

**Files:**

- Create: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] Render summary metrics.
- [ ] Render books table with scan actions.
- [ ] Render specific scan form.
- [ ] Render settings form.
- [ ] Render active/recent jobs.

### Task 8: Verification

**Files:**

- Create: `README.md`

- [ ] Run `python -m py_compile` on backend modules.
- [ ] Run `npm install` and `npm run build` in `frontend`.
- [ ] Start backend and frontend dev servers.
- [ ] Verify the UI loads and API health endpoint returns ok.
- [ ] Document server deployment environment variables.
