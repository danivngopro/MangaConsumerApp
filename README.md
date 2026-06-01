# Asura Komga Manager

Local fullstack app for scanning Asura Scans, indexing a Komga books folder, and queueing missing chapter downloads as CBZ files.

## Configuration

Copy `.env.example` to `.env` and adjust paths.

On this development PC, the default library root can be:

```text
\\192.168.1.139\Ext3TDrive3\komga\books
```

On the home server, set `MANGA_LIBRARY_ROOT` to the server-local path that points to the same Komga books directory.

Set Komga connection settings in `.env`:

```text
KOMGA_URL=http://localhost:25600
KOMGA_USERNAME=your-komga-user
KOMGA_PASSWORD=your-komga-password
KOMGA_BOOKS_ROOT_DOCKER=/books
```

`KOMGA_BOOKS_ROOT_DOCKER` is the path Komga sees inside Docker. The backend maps a downloaded folder like `{MANGA_LIBRARY_ROOT}/Book Name` to `/books/Book Name` when creating or scanning a Komga library.

If you run this app on your PC while Komga runs on `192.168.1.139`, set:

```text
KOMGA_URL=http://192.168.1.139:25600
```

`http://localhost:25600` only works when Komga is reachable from the same machine/container as the backend.

## Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8816
```

Health check:

```text
http://localhost:8816/api/health
```

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## Docker

Edit `docker-compose.yml` before first run:

- Set `KOMGA_USERNAME` and `KOMGA_PASSWORD`.
- On Linux, replace the `//192.168.1.139/...:/books` volume with the server-local books path, for example `/media/danivngopro/Ext3TDrive3/komga/books:/books`.
- Keep `APP_DATA_DIR=/data`; SQLite is stored in the container volume mount `./data:/data`.

Build and run:

```powershell
docker compose up --build
```

Open:

```text
http://localhost:8816
```

The first page load asks you to register the single owner account. After that, registration is disabled and only login is allowed.

## Notes

- Full scans automatically enqueue newly discovered titles and missing chapters.
- Existing `.cbz` files are not overwritten.
- Download workers can be changed from the UI. Keep it low; 1-3 is the practical range for Asura.
- The downloader defaults to one worker to avoid hammering Asura.
- After the last queued download for a new book finishes, the backend creates/syncs the Komga library and triggers a quick `deep=false` scan.
- After the last queued download for an existing book finishes, the backend triggers a quick `deep=false` Komga scan for that book's library.
- The UI has manual quick scan buttons for a single book and for all Komga libraries. The all-library scan asks for confirmation first.
- Asura changes its site often; parser or Cloudflare failures are stored in the backend logs/jobs instead of silently ignored.
