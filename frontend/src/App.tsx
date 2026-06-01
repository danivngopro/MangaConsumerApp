import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  BookOpen,
  Clock,
  Download,
  Pause,
  Play,
  RefreshCw,
  Info,
  Search,
  Server,
  Lock,
  Settings,
} from "lucide-react";
import { api, AuthStatus, Book, BookDetail, DownloadProgress, Job, Summary } from "./api";

const emptySummary: Summary = {
  knownManga: 0,
  localBooks: 0,
  localChapters: 0,
  queuedJobs: 0,
  runningJobs: 0,
  failedJobs: 0,
  pausedJobs: 0,
  missingChapters: 0,
  lastScanAt: null,
  queuePaused: false,
  libraryRoot: "",
  komgaUrl: "",
  autoScanEveryDays: 0,
  downloadConcurrency: 1,
};

export function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [summary, setSummary] = useState<Summary>(emptySummary);
  const [books, setBooks] = useState<Book[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [progress, setProgress] = useState<DownloadProgress[]>([]);
  const [selectedBook, setSelectedBook] = useState<BookDetail | null>(null);
  const [query, setQuery] = useState("");
  const [scanLimit, setScanLimit] = useState(10);
  const [intervalDays, setIntervalDays] = useState(0);
  const [downloadConcurrency, setDownloadConcurrency] = useState(1);
  const [status, setStatus] = useState("Ready");
  const [loading, setLoading] = useState(false);

  async function refresh() {
    const nextAuthStatus = await api.authStatus();
    setAuthStatus(nextAuthStatus);
    if (!nextAuthStatus.authenticated) {
      return;
    }
    const [nextSummary, nextBooks, nextJobs, nextProgress] = await Promise.all([
      api.summary(),
      api.books(),
      api.jobs(),
      api.progress(),
    ]);
    setSummary(nextSummary);
    setBooks(nextBooks);
    setJobs(nextJobs);
    setProgress(nextProgress);
    setIntervalDays(nextSummary.autoScanEveryDays);
    setDownloadConcurrency(nextSummary.downloadConcurrency);
  }

  useEffect(() => {
    refresh().catch((error) => setStatus(error.message));
    const handle = window.setInterval(() => {
      refresh().catch((error) => setStatus(error.message));
    }, 5000);
    return () => window.clearInterval(handle);
  }, []);

  const activeJobs = useMemo(
    () => jobs.filter((job) => job.status === "running" || job.status === "queued").slice(0, 8),
    [jobs],
  );

  async function runAction(label: string, action: () => Promise<unknown>) {
    setLoading(true);
    setStatus(label);
    try {
      await action();
      await refresh();
      setStatus(`${label} started`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  async function submitSpecific(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    await runAction("Specific scan", () => api.specificScan(query.trim()));
    setQuery("");
  }

  async function submitSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction("Settings update", () => api.updateSettings(intervalDays, downloadConcurrency));
  }

  async function confirmAllKomgaScan() {
    const ok = window.confirm(
      "Run a quick Komga scan for every library? This is not a deep scan, but it can still be heavy.",
    );
    if (!ok) return;
    await runAction("Komga quick scan all", api.quickScanAll);
  }

  async function openBook(bookId: number) {
    try {
      setSelectedBook(await api.bookDetail(bookId));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function pauseOrResumeBook(book: Book) {
    const detail = selectedBook?.id === book.id ? selectedBook : await api.bookDetail(book.id);
    if (detail.paused_downloads) {
      await runAction(`Resume downloads: ${book.title}`, () => api.resumeBookDownloads(book.id));
    } else {
      await runAction(`Pause downloads: ${book.title}`, () => api.pauseBookDownloads(book.id));
    }
    if (selectedBook?.id === book.id) {
      setSelectedBook(await api.bookDetail(book.id));
    }
  }

  if (!authStatus) {
    return <main className="app-shell"><div className="panel">Loading...</div></main>;
  }

  if (!authStatus.authenticated) {
    return <AuthScreen authStatus={authStatus} onAuthenticated={refresh} />;
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Asura Komga Manager</h1>
          <p>{summary.libraryRoot || "Backend not connected"}</p>
          <p>Logged in as {authStatus.username}</p>
        </div>
        <div className="topbar-actions">
          <button className="secondary" onClick={() => refresh()} disabled={loading} title="Refresh">
            <RefreshCw size={17} />
            Refresh
          </button>
          <button
            className={summary.queuePaused ? "primary" : "secondary"}
            onClick={() => runAction(summary.queuePaused ? "Queue resume" : "Queue pause", summary.queuePaused ? api.resumeQueue : api.pauseQueue)}
            disabled={loading}
            title={summary.queuePaused ? "Resume all queued downloads" : "Pause all queued downloads after current running chapters finish"}
          >
            {summary.queuePaused ? <Play size={17} /> : <Pause size={17} />}
            {summary.queuePaused ? "Resume all downloads" : "Pause all downloads"}
          </button>
          <button
            className="secondary"
            onClick={() => runAction("Logout", async () => {
              await api.logout();
              setAuthStatus(await api.authStatus());
            })}
            disabled={loading}
          >
            Logout
          </button>
        </div>
      </header>

      <section className="metrics">
        <Metric icon={<BookOpen />} label="Local books" value={summary.localBooks} />
        <Metric icon={<Download />} label="Local chapters" value={summary.localChapters} />
        <Metric icon={<Search />} label="Known Asura titles" value={summary.knownManga} />
        <Metric icon={<Clock />} label="Missing chapters" value={summary.missingChapters} />
        <Metric icon={<Activity />} label="Queued" value={summary.queuedJobs + summary.runningJobs} />
        <Metric icon={<Pause />} label="Paused" value={summary.pausedJobs} />
        <Metric icon={<Server />} label="Failed" value={summary.failedJobs} tone={summary.failedJobs ? "warn" : "normal"} />
      </section>

      <section className="control-grid">
        <div className="panel">
          <div className="panel-title">
            <RefreshCw size={18} />
            Scan Controls
          </div>
          <div className="button-row">
            <button
              className="primary"
              onClick={() => runAction("Full scan", () => api.fullScan(null))}
              disabled={loading}
              title="Scan every Asura catalog page, compare against your Komga books folder, and enqueue every missing chapter. This can queue a lot."
            >
              Full scan
            </button>
            <button
              className="secondary"
              onClick={() => runAction("Library scan", api.libraryScan)}
              disabled={loading}
              title="Re-read the local Komga books folder and count existing CBZ chapters. This does not call Komga and does not download."
            >
              Reindex library
            </button>
            <button
              className="secondary"
              onClick={confirmAllKomgaScan}
              disabled={loading}
              title="Ask Komga to quick scan every existing Komga library with deep=false. This can be heavy, so confirmation is required."
            >
              Komga scan all
            </button>
          </div>
          <div className="limited-scan">
            <label title="Scan only the first N books from Asura Browse. Useful for testing without queueing the entire catalog.">
              Scan first
              <input
                type="number"
                min={1}
                max={500}
                value={scanLimit}
                onChange={(event) => setScanLimit(Number(event.target.value))}
              />
              books
            </label>
            <button
              className="secondary"
              onClick={() => runAction(`Scan first ${scanLimit} books`, () => api.fullScan(scanLimit))}
              disabled={loading}
              title="Scan only this many Asura books, then enqueue missing chapters for those books."
            >
              Limited scan
            </button>
          </div>
          <form className="inline-form" onSubmit={submitSpecific}>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Manga title or Asura URL"
            />
            <button className="secondary" disabled={loading || !query.trim()}>
              Scan manga
            </button>
          </form>
          <p className="status-line">{status}</p>
          <p className="muted">Komga: {summary.komgaUrl || "not configured"}</p>
        </div>

        <div className="panel">
          <div className="panel-title">
            <Settings size={18} />
            Settings
          </div>
          <form className="settings-form" onSubmit={submitSettings}>
            <label>
              Auto scan every
              <input
                type="number"
                min={0}
                value={intervalDays}
                onChange={(event) => setIntervalDays(Number(event.target.value))}
              />
              days
            </label>
            <label>
              Concurrent downloads
              <input
                type="number"
                min={1}
                max={6}
                value={downloadConcurrency}
                onChange={(event) => setDownloadConcurrency(Number(event.target.value))}
              />
            </label>
            <button className="secondary" disabled={loading}>Save</button>
          </form>
          <p className="muted">
            Auto scan 0 disables scheduling. Concurrent downloads controls parallel chapter download workers. Keep it low; 1-3 is usually enough. Last scan: {summary.lastScanAt ? new Date(summary.lastScanAt).toLocaleString() : "never"}
          </p>
        </div>
      </section>

      <section className="panel progress-panel">
        <div className="panel-title">
          <Info size={18} />
          Download Progress
        </div>
        {progress.length ? (
          <div className="progress-list">
            {progress.map((item) => <ProgressRow key={item.manga_id} item={item} />)}
          </div>
        ) : (
          <p className="empty">No download progress yet.</p>
        )}
      </section>

      <section className="content-grid">
        <div className="panel books-panel">
          <div className="panel-title">
            <BookOpen size={18} />
            Downloaded and Tracked Books
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Local</th>
                  <th>Asura</th>
                  <th>Missing</th>
                  <th>Last scan</th>
                  <th>Downloads</th>
                  <th>Komga</th>
                </tr>
              </thead>
              <tbody>
                {books.map((book) => (
                  <tr key={book.id}>
                    <td>
                      <a href={book.url} target="_blank" rel="noreferrer">{book.title}</a>
                      <span>{book.local_folder ?? "Not in local library yet"}</span>
                    </td>
                    <td>{book.status ?? "unknown"}</td>
                    <td>{book.local_chapter_count}</td>
                    <td>{book.remote_chapter_count}</td>
                    <td className={book.missing_count > 0 ? "missing" : ""}>{book.missing_count}</td>
                    <td>{book.last_scanned_at ? new Date(book.last_scanned_at).toLocaleString() : "never"}</td>
                    <td>
                      <div className="book-actions">
                        <button
                          className="mini-button"
                          onClick={() => openBook(book.id)}
                          disabled={loading}
                        >
                          Details
                        </button>
                        <button
                          className="mini-button"
                          onClick={() => pauseOrResumeBook(book)}
                          disabled={loading}
                        >
                          Pause
                        </button>
                      </div>
                    </td>
                    <td>
                      <button
                        className="mini-button"
                        onClick={() => runAction(`Komga quick scan: ${book.title}`, () => api.quickScanBook(book.id))}
                        disabled={loading}
                      >
                        Quick scan
                      </button>
                    </td>
                  </tr>
                ))}
                {!books.length && (
                  <tr>
                    <td colSpan={8} className="empty">Run a full scan to populate tracked books.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel jobs-panel">
          <div className="panel-title">
            <Activity size={18} />
            Queue
          </div>
          <div className="job-list">
            {activeJobs.map((job) => <JobRow key={job.id} job={job} />)}
            {!activeJobs.length && <p className="empty">No active jobs.</p>}
          </div>
          <div className="recent">
            <h2>Recent</h2>
            {jobs.slice(0, 12).map((job) => <JobRow key={`recent-${job.id}`} job={job} compact />)}
          </div>
        </div>
      </section>
      {selectedBook && (
        <BookDetailPanel
          book={selectedBook}
          onClose={() => setSelectedBook(null)}
          onRefresh={() => openBook(selectedBook.id)}
        />
      )}
    </main>
  );
}

function ProgressRow({ item }: { item: DownloadProgress }) {
  return (
    <div className="progress-row">
      <div className="progress-header">
        <strong>{item.manga_title}</strong>
        <span>
          {item.done}/{item.total} episodes downloaded
          {item.running ? `, ${item.running} running` : ""}
          {item.failed ? `, ${item.failed} failed` : ""}
        </span>
      </div>
      <div className="progress-track" aria-label={`${item.percent}% complete`}>
        <div className="progress-fill" style={{ width: `${Math.min(100, item.percent)}%` }} />
      </div>
      <em>{item.percent}%</em>
    </div>
  );
}

function BookDetailPanel({ book, onClose, onRefresh }: { book: BookDetail; onClose: () => void; onRefresh: () => void }) {
  const downloadedPaths = book.chapters.filter((chapter) => chapter.is_downloaded && chapter.file_path);
  return (
    <div className="detail-backdrop" role="dialog" aria-modal="true">
      <section className="detail-panel">
        <header className="detail-header">
          <div>
            <h2>{book.title}</h2>
            <p>{book.local_folder ?? "No local folder recorded yet"}</p>
          </div>
          <div className="button-row">
            <button className="secondary" onClick={onRefresh}>Refresh</button>
            <button className="secondary" onClick={onClose}>Close</button>
          </div>
        </header>
        <div className="detail-grid">
          <DetailStat label="Downloaded episodes" value={`${book.downloaded_count} / ${book.remote_chapter_count || book.chapters.length}`} />
          <DetailStat label="Local path" value={book.local_folder ?? "Not created yet"} />
          <DetailStat label="Downloads paused" value={book.paused_downloads ? "Yes" : "No"} />
          <DetailStat label="Komga library ID" value={book.komga_library_id ?? "Not recorded"} />
          <DetailStat label="Komga import ran" value={book.komga_imported_at ? new Date(book.komga_imported_at).toLocaleString() : "No"} />
          <DetailStat label="Komga quick scan ran" value={book.komga_scanned_at ? new Date(book.komga_scanned_at).toLocaleString() : "No"} />
          <DetailStat label="Komga last error" value={book.komga_last_error ?? "None"} />
        </div>
        <h3>Downloaded files</h3>
        <div className="path-list">
          {downloadedPaths.map((chapter) => (
            <div key={chapter.id}>
              <strong>{chapter.label}</strong>
              <span>{chapter.file_path}</span>
            </div>
          ))}
          {!downloadedPaths.length && <p className="empty">No downloaded chapter paths recorded yet.</p>}
        </div>
      </section>
    </div>
  );
}

function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AuthScreen({ authStatus, onAuthenticated }: { authStatus: AuthStatus; onAuthenticated: () => Promise<void> }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const mode = authStatus.registrationOpen ? "register" : "login";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      if (mode === "register") {
        await api.register(username.trim(), password);
      } else {
        await api.login(username.trim(), password);
      }
      await onAuthenticated();
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="auth-panel" onSubmit={submit}>
        <div className="auth-icon"><Lock size={22} /></div>
        <h1>{mode === "register" ? "Create owner account" : "Log in"}</h1>
        <p>
          {mode === "register"
            ? "First startup requires one owner account. Registration closes after this user is created."
            : "Registration is closed. Use the owner account to continue."}
        </p>
        <label>
          Username
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
        </label>
        <label>
          Password
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete={mode === "register" ? "new-password" : "current-password"}
          />
        </label>
        {error && <div className="auth-error">{error}</div>}
        <button className="primary" disabled={loading || !username.trim() || !password}>
          {mode === "register" ? "Register owner" : "Log in"}
        </button>
      </form>
    </main>
  );
}

function Metric({ icon, label, value, tone = "normal" }: { icon: JSX.Element; label: string; value: number; tone?: "normal" | "warn" }) {
  return (
    <div className={`metric ${tone}`}>
      <div className="metric-icon">{icon}</div>
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  );
}

function JobRow({ job, compact = false }: { job: Job; compact?: boolean }) {
  return (
    <div className={`job-row ${job.status} ${compact ? "compact" : ""}`}>
      <div>
        <strong>{job.manga_title ?? job.type}</strong>
        <span>{job.chapter_label ?? `Job ${job.id}`}</span>
        {job.error && <small>{job.error}</small>}
      </div>
      <em>{job.status}</em>
    </div>
  );
}
