# Manga Crawler Design

## Goal

Build a local fullstack app that scans Asura Scans, indexes a Komga library, and automatically downloads missing manga titles and new chapters into a configured books folder.

## Runtime Target

The app will be developed on this PC but is intended to run on the home server at `192.168.1.139`. The library path must be configurable through `MANGA_LIBRARY_ROOT`.

Development default:

```text
\\192.168.1.139\Ext3TDrive3\komga\books
```

Home-server deployment should set `MANGA_LIBRARY_ROOT` to the server-local path for the same folder.

## Architecture

The backend is a FastAPI service with SQLite persistence. It owns all scanning, queueing, download, scheduling, and filesystem access. The frontend is a Vite React app that calls the backend API and shows library state, scan controls, queue state, and settings.

The existing `asuraScansCrawlerWithThreads.py` behavior is refactored into importable downloader code. HTTP parsing is used for catalog and chapter metadata. Selenium is reserved for reader pages where image URLs are loaded dynamically.

## Backend Responsibilities

- Scan the local Komga books root and count `.cbz` files per title.
- Crawl `https://asurascans.com/browse?page=N` until no next page is found.
- Parse Asura series cards for title, URL, cover, status, chapter count, and latest chapter hints.
- Scan a specific manga by URL, slug, or title search.
- Parse series pages for chapter URLs and chapter numbers.
- Compare remote chapters to local CBZ files using normalized title and chapter-number matching.
- Automatically enqueue missing chapters, including all chapters for newly discovered titles.
- Download queued chapters with retry, durable status, and conservative concurrency.
- Store settings, scan history, queue jobs, manga records, chapter records, and recent logs in SQLite.
- Run automatic full scans every configured number of days.

## Frontend Responsibilities

- Show summary counts: local books, downloaded chapters, known Asura titles, queued chapters, failed jobs, and last scan time.
- Show a books table with local count, remote count, missing count, status, last scanned, and actions.
- Allow manual full scan.
- Allow specific manga scan.
- Allow queue pause/resume.
- Allow setting automatic full scan interval in days.
- Show active and recent download jobs.

## Safety Rules

- Never overwrite an existing `.cbz`.
- Use a sanitized folder name derived from the manga title.
- Store download state before starting a chapter so crashes can be resumed.
- Retry failed downloads three times, then mark the job failed with the error message.
- Keep downloader concurrency configurable and default it to `1`.
- Treat Asura HTML/API shape as unstable; parser failures should become visible job errors, not silent skips.

## Output Format

Downloaded chapters are saved as:

```text
{MANGA_LIBRARY_ROOT}/{Sanitized Manga Title}/{Sanitized Manga Title} - Chapter {chapter_number}.cbz
```

Temporary image files are written under the app data directory and removed after CBZ creation.
