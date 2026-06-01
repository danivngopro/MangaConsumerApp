import { FormEvent, useEffect, useState } from "react";
import {
  Activity,
  BookOpen,
  ChevronDown,
  Clock,
  Download,
  Info,
  Lock,
  Pause,
  Play,
  RefreshCw,
  Search,
  Server,
  Settings,
  UploadCloud,
  X,
  Zap,
} from "lucide-react";
import { api, AuthStatus, BookDetail, BrowseFilters, BrowseResult, DownloadProgress, Summary } from "./api";

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
  const [progress, setProgress] = useState<DownloadProgress[]>([]);
  const [details, setDetails] = useState<Record<number, BookDetail>>({});
  const [expandedBookId, setExpandedBookId] = useState<number | null>(null);
  const [browseFilters, setBrowseFilters] = useState<BrowseFilters | null>(null);
  const [browseResults, setBrowseResults] = useState<BrowseResult[]>([]);
  const [browseTotal, setBrowseTotal] = useState(0);
  const [browseOffset, setBrowseOffset] = useState(0);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseSearch, setBrowseSearch] = useState("");
  const [browseGenres, setBrowseGenres] = useState<string[]>([]);
  const [browseStatus, setBrowseStatus] = useState("all");
  const [browseType, setBrowseType] = useState("all");
  const [browseSort, setBrowseSort] = useState("latest");
  const [browseOrder, setBrowseOrder] = useState("desc");
  const [browseAuthor, setBrowseAuthor] = useState("");
  const [browseArtist, setBrowseArtist] = useState("");
  const [browseMinChapters, setBrowseMinChapters] = useState(0);
  const [hideExisting, setHideExisting] = useState(true);
  const [hideStringText, setHideStringText] = useState("");
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
    const [nextSummary, nextProgress] = await Promise.all([api.summary(), api.progress()]);
    setSummary(nextSummary);
    setProgress(nextProgress);
    setIntervalDays(nextSummary.autoScanEveryDays);
    setDownloadConcurrency(nextSummary.downloadConcurrency);
    if (!browseFilters) {
      setBrowseFilters(await api.asuraFilters());
    }
    if (expandedBookId) {
      const detail = await api.bookDetail(expandedBookId);
      setDetails((current) => ({ ...current, [expandedBookId]: detail }));
    }
  }

  useEffect(() => {
    refresh().catch((error) => setStatus(error.message));
    const handle = window.setInterval(() => {
      refresh().catch((error) => setStatus(error.message));
    }, 5000);
    return () => window.clearInterval(handle);
  }, [expandedBookId, browseFilters]);

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

  function browsePayload(offset = 0) {
    return {
      search: browseSearch.trim(),
      genres: browseGenres,
      author: browseAuthor.trim(),
      artist: browseArtist.trim(),
      status: browseStatus,
      type: browseType,
      sort: browseSort,
      order: browseOrder,
      minChapters: browseMinChapters,
      limit: 24,
      offset,
    };
  }

  async function submitBrowseSearch(event?: FormEvent<HTMLFormElement>, offset = 0) {
    event?.preventDefault();
    setBrowseLoading(true);
    setStatus("Searching Asura");
    try {
      const result = await api.asuraSearch(browsePayload(offset));
      setBrowseResults(result.items);
      setBrowseTotal(result.total);
      setBrowseOffset(result.offset);
      setStatus(`Found ${result.total.toLocaleString()} Asura books`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBrowseLoading(false);
    }
  }

  function toggleGenre(slug: string) {
    setBrowseGenres((current) => current.includes(slug) ? current.filter((item) => item !== slug) : [...current, slug]);
  }

  const hiddenStrings = hideStringText
    .split(/\r?\n|,/)
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  const visibleBrowseResults = browseResults.filter((item) => {
    if (hideExisting && item.is_existing) return false;
    if (hiddenStrings.some((part) => item.title.toLowerCase().includes(part))) return false;
    return true;
  });

  async function toggleBook(bookId: number) {
    if (expandedBookId === bookId) {
      setExpandedBookId(null);
      return;
    }
    setExpandedBookId(bookId);
    if (!details[bookId]) {
      setDetails((current) => ({ ...current }));
      try {
        const detail = await api.bookDetail(bookId);
        setDetails((current) => ({ ...current, [bookId]: detail }));
      } catch (error) {
        setStatus(error instanceof Error ? error.message : String(error));
      }
    }
  }

  async function refreshBook(bookId: number) {
    const detail = await api.bookDetail(bookId);
    setDetails((current) => ({ ...current, [bookId]: detail }));
  }

  async function pauseOrResumeBook(item: DownloadProgress, detail?: BookDetail) {
    if (detail?.paused_downloads || item.paused > 0) {
      await runAction(`Resume downloads: ${item.manga_title}`, () => api.resumeBookDownloads(item.manga_id));
    } else {
      await runAction(`Pause downloads: ${item.manga_title}`, () => api.pauseBookDownloads(item.manga_id));
    }
    if (expandedBookId === item.manga_id) {
      await refreshBook(item.manga_id);
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
        <div className="brand-block">
          <img className="site-mark" src="/site-icon.png" alt="" />
          <div>
            <h1>Asura Komga Manager</h1>
            <p>{summary.libraryRoot || "Backend not connected"}</p>
            <p>Logged in as {authStatus.username}</p>
          </div>
        </div>
        <div className="topbar-actions">
          <button className="secondary" onClick={() => refresh()} disabled={loading} title="Refresh dashboard data now.">
            <RefreshCw size={17} />
            Refresh
          </button>
          <button
            className={summary.queuePaused ? "primary" : "secondary"}
            onClick={() => runAction(summary.queuePaused ? "Queue resume" : "Queue pause", summary.queuePaused ? api.resumeQueue : api.pauseQueue)}
            disabled={loading}
            title={summary.queuePaused ? "Resume all queued downloads." : "Pause all queued downloads after current running chapters finish."}
          >
            {summary.queuePaused ? <Play size={17} /> : <Pause size={17} />}
            {summary.queuePaused ? "Resume all" : "Pause all"}
          </button>
          <button
            className="secondary"
            onClick={() => runAction("Retry failed downloads", api.retryFailedDownloads)}
            disabled={loading || summary.failedJobs === 0}
            title="Requeue failed chapter downloads and reset their attempt count."
          >
            Retry failed
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
              title="Scan the full Asura catalog, compare against your Komga books folder, and enqueue missing chapters."
            >
              Full scan
            </button>
            <button
              className="secondary"
              onClick={() => runAction("Library reindex", api.libraryScan)}
              disabled={loading}
              title="Re-read the local Komga books folder and count existing CBZ chapters. This does not call Komga."
            >
              Reindex library
            </button>
            <button
              className="secondary"
              onClick={confirmAllKomgaScan}
              disabled={loading}
              title="Ask Komga to quick scan every existing Komga library with deep=false. Confirmation is required."
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
            <button className="secondary" disabled={loading || !query.trim()} title="Find one Asura manga, compare it against local files, and enqueue missing chapters.">
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
            Auto scan 0 disables scheduling. Concurrent downloads controls parallel chapter workers. Last scan: {summary.lastScanAt ? new Date(summary.lastScanAt).toLocaleString() : "never"}
          </p>
        </div>
      </section>

      <section className="panel search-panel">
        <div className="panel-title">
          <Search size={18} />
          Asura Search
        </div>
        <form className="browse-form" onSubmit={(event) => submitBrowseSearch(event, 0)}>
          <input
            value={browseSearch}
            onChange={(event) => setBrowseSearch(event.target.value)}
            placeholder="Search Asura titles"
            title="Search Asura by title."
          />
          <select value={browseStatus} onChange={(event) => setBrowseStatus(event.target.value)} title="Filter by Asura status.">
            {(browseFilters?.statuses ?? ["all", "ongoing", "completed", "hiatus", "dropped", "axed"]).map((status) => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
          <select value={browseType} onChange={(event) => setBrowseType(event.target.value)} title="Filter by series type.">
            {(browseFilters?.types ?? ["all", "manhwa", "manhua", "manga"]).map((type) => (
              <option key={type} value={type}>{type}</option>
            ))}
          </select>
          <select value={browseSort} onChange={(event) => setBrowseSort(event.target.value)} title="Sort Asura results.">
            {(browseFilters?.sorts ?? ["latest", "popular", "rating", "title", "chapters"]).map((sort) => (
              <option key={sort} value={sort}>{sort}</option>
            ))}
          </select>
          <select value={browseOrder} onChange={(event) => setBrowseOrder(event.target.value)} title="Sort direction.">
            <option value="desc">desc</option>
            <option value="asc">asc</option>
          </select>
          <input
            type="number"
            min={0}
            value={browseMinChapters}
            onChange={(event) => setBrowseMinChapters(Number(event.target.value))}
            placeholder="Min chapters"
            title="Minimum chapter count."
          />
          <input value={browseAuthor} onChange={(event) => setBrowseAuthor(event.target.value)} placeholder="Author" title="Filter by author." />
          <input value={browseArtist} onChange={(event) => setBrowseArtist(event.target.value)} placeholder="Artist" title="Filter by artist." />
          <button className="primary" disabled={browseLoading} title="Search Asura using the selected filters.">
            Search
          </button>
        </form>

        <div className="filter-options">
          <label title="Hide books already found in your local Komga folder.">
            <input type="checkbox" checked={hideExisting} onChange={(event) => setHideExisting(event.target.checked)} />
            Hide existing books
          </label>
          <label className="hide-strings" title="Comma or newline separated strings. Any matching title is hidden from the results.">
            Hide titles containing
            <textarea value={hideStringText} onChange={(event) => setHideStringText(event.target.value)} placeholder="academy, regression, necromancer" />
          </label>
        </div>

        <div className="genre-strip">
          {(browseFilters?.genres ?? []).map((genre) => (
            <button
              key={genre.slug}
              type="button"
              className={browseGenres.includes(genre.slug) ? "chip selected" : "chip"}
              onClick={() => toggleGenre(genre.slug)}
              title={`Toggle ${genre.name} genre filter.`}
            >
              {genre.name}
            </button>
          ))}
        </div>

        <div className="search-results-header">
          <span>
            Showing {visibleBrowseResults.length} of {browseResults.length} loaded results
            {browseTotal ? `, ${browseTotal.toLocaleString()} total from Asura` : ""}
          </span>
          <div className="button-row">
            <button className="secondary" disabled={browseLoading || browseOffset === 0} onClick={() => submitBrowseSearch(undefined, Math.max(0, browseOffset - 24))} title="Load previous Asura result page.">Previous</button>
            <button className="secondary" disabled={browseLoading || browseOffset + 24 >= browseTotal} onClick={() => submitBrowseSearch(undefined, browseOffset + 24)} title="Load next Asura result page.">Next</button>
          </div>
        </div>

        <div className="browse-results">
          {visibleBrowseResults.map((item) => (
            <BrowseResultRow
              key={item.id}
              item={item}
              loading={loading || browseLoading}
              onAdd={() => runAction(`Add book: ${item.title}`, () => api.specificScan(item.url))}
            />
          ))}
          {!visibleBrowseResults.length && <p className="empty">No visible search results yet.</p>}
        </div>
      </section>

      <section className="panel progress-panel">
        <div className="panel-title">
          <Info size={18} />
          Books and Download Progress
        </div>
        {progress.length ? (
          <div className="progress-list">
            {progress.map((item) => (
              <ProgressRow
                key={item.manga_id}
                item={item}
                detail={details[item.manga_id]}
                expanded={expandedBookId === item.manga_id}
                loading={loading}
                onToggle={() => toggleBook(item.manga_id)}
                onRefresh={() => runAction(`Refresh: ${item.manga_title}`, () => refreshBook(item.manga_id))}
                onClose={() => setExpandedBookId(null)}
                onPause={() => pauseOrResumeBook(item, details[item.manga_id])}
                onQuickScan={() => runAction(`Fast Komga scan: ${item.manga_title}`, () => api.quickScanBook(item.manga_id))}
                onImport={() => runAction(`Komga import: ${item.manga_title}`, () => api.importBook(item.manga_id))}
                onRetryFailed={() => runAction(`Retry failed: ${item.manga_title}`, () => api.retryFailedBookDownloads(item.manga_id))}
                onSpecificScan={() => runAction(`Quick scan: ${item.manga_title}`, () => api.specificScan(item.url || item.manga_title))}
              />
            ))}
          </div>
        ) : (
          <p className="empty">No tracked books yet. Run a scan to populate progress.</p>
        )}
      </section>
    </main>
  );
}

function ProgressRow({
  item,
  detail,
  expanded,
  loading,
  onToggle,
  onRefresh,
  onClose,
  onPause,
  onQuickScan,
  onImport,
  onRetryFailed,
  onSpecificScan,
}: {
  item: DownloadProgress;
  detail?: BookDetail;
  expanded: boolean;
  loading: boolean;
  onToggle: () => void;
  onRefresh: () => void;
  onClose: () => void;
  onPause: () => void;
  onQuickScan: () => void;
  onImport: () => void;
  onRetryFailed: () => void;
  onSpecificScan: () => void;
}) {
  const paused = Boolean(detail?.paused_downloads || item.paused > 0);
  const localChapters = detail?.local_chapters ?? [];
  const newlyDownloaded = detail?.chapters.filter((chapter) => chapter.is_downloaded && chapter.file_path) ?? [];
  const episodeTotal = item.remote_chapter_count || item.total || detail?.chapters.length || 0;
  const downloaded = detail?.downloaded_count ?? item.available_count ?? item.done;

  return (
    <article className={`progress-row ${expanded ? "expanded" : ""}`}>
      <button className="progress-main" onClick={onToggle} title="Open episode list and book actions.">
        <div className="progress-header">
          <div>
            <strong>{item.manga_title}</strong>
            <span>{item.local_folder ?? "Not in local library yet"}</span>
          </div>
          <em>
            {downloaded}/{episodeTotal} episodes
            {item.running ? `, ${item.running} running` : ""}
          </em>
        </div>
        <div className="progress-track" aria-label={`${item.percent}% complete`}>
          <div className="progress-fill" style={{ width: `${Math.min(100, item.percent)}%` }} />
        </div>
        <div className="progress-meta">
          <span>{item.percent}%</span>
          <span>{item.queued} queued</span>
          <span>{item.paused} paused</span>
          <span>{item.failed} failed</span>
        </div>
        <ChevronDown className="progress-chevron" size={18} />
      </button>

      {expanded && (
        <div className="book-dropdown">
          <div className="book-action-bar">
            <IconButton icon={<RefreshCw size={16} />} label="Refresh" title="Refresh this book's details." onClick={onRefresh} disabled={loading} />
            <IconButton icon={<X size={16} />} label="Close" title="Close this book dropdown." onClick={onClose} disabled={loading} />
            <IconButton icon={paused ? <Play size={16} /> : <Pause size={16} />} label={paused ? "Resume" : "Pause"} title="Pause or resume queued downloads for this book. Running chapters finish first." onClick={onPause} disabled={loading} />
            <IconButton icon={<Search size={16} />} label="Quick scan" title="Scan this manga on Asura and enqueue any newly missing chapters." onClick={onSpecificScan} disabled={loading} />
            <IconButton icon={<RefreshCw size={16} />} label="Retry failed" title="Requeue failed chapter downloads for this book." onClick={onRetryFailed} disabled={loading || item.failed === 0} />
            <IconButton icon={<UploadCloud size={16} />} label="Import" title="Create or find this book's Komga library without forcing a scan." onClick={onImport} disabled={loading} />
            <IconButton icon={<Zap size={16} />} label="Fast scan" title="Run Komga quick scan for this book with deep=false." onClick={onQuickScan} disabled={loading} />
          </div>

          <div className="episode-summary">
            <DetailStat label="Status" value={detail?.status ?? "unknown"} />
            <DetailStat label="Local" value={`${detail?.local_chapter_count ?? item.existing_downloaded_count} episodes`} />
            <DetailStat label="Asura" value={`${detail?.remote_chapter_count ?? item.remote_chapter_count} episodes`} />
            <DetailStat label="Missing" value={`${detail?.missing_count ?? item.missing_count} episodes`} />
            <DetailStat label="Existing on server" value={`${detail?.existing_downloaded_count ?? item.existing_downloaded_count} episodes`} />
            <DetailStat label="Newly downloaded" value={`${detail?.newly_downloaded_count ?? item.newly_downloaded_count} episodes`} />
            <DetailStat label="Storage path" value={detail?.local_folder ?? item.local_folder ?? "Not created yet"} />
            <DetailStat label="Komga import" value={detail?.komga_imported_at ? new Date(detail.komga_imported_at).toLocaleString() : "Not recorded"} />
            <DetailStat label="Fast library scan" value={detail?.komga_scanned_at ? new Date(detail.komga_scanned_at).toLocaleString() : "Not recorded"} />
            <DetailStat label="Komga error" value={detail?.komga_last_error ?? "None"} />
          </div>

          <div className="episode-list">
            {localChapters.map((chapter) => (
              <div key={`local-${chapter}`} className="episode-row existing">
                <strong>Chapter {chapter}</strong>
                <span>Existing on server</span>
              </div>
            ))}
            {newlyDownloaded.map((chapter) => (
              <div key={`new-${chapter.id}`} className="episode-row new">
                <strong>{chapter.label}</strong>
                <span>{chapter.file_path}</span>
              </div>
            ))}
            {!detail && <p className="empty">Loading episodes...</p>}
            {detail && !localChapters.length && !newlyDownloaded.length && (
              <p className="empty">No downloaded episode paths recorded yet.</p>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

function BrowseResultRow({ item, loading, onAdd }: { item: BrowseResult; loading: boolean; onAdd: () => void }) {
  return (
    <div className="browse-result-row">
      {item.cover_url ? <img src={item.cover_url} alt="" loading="lazy" /> : <div className="cover-placeholder"><BookOpen size={20} /></div>}
      <div>
        <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>
        <span>{[item.status, item.type, `${item.chapter_count} chapters`].filter(Boolean).join(" · ")}</span>
        <small>{item.genres.map((genre) => genre.name).join(", ") || "No genres listed"}</small>
        {item.local_folder && <small>{item.local_folder}</small>}
      </div>
      <div className="browse-counts">
        <DetailStat label="Local" value={`${item.local_chapter_count}`} />
        <DetailStat label="Asura" value={`${item.chapter_count}`} />
        <DetailStat label="Missing" value={`${item.missing_count}`} />
      </div>
      <button className="primary" onClick={onAdd} disabled={loading} title="Add this book by scanning it and queueing missing chapters.">
        Add
      </button>
    </div>
  );
}

function IconButton({ icon, label, title, onClick, disabled }: { icon: JSX.Element; label: string; title: string; onClick: () => void; disabled: boolean }) {
  return (
    <button
      className="mini-button"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      disabled={disabled}
      title={title}
    >
      {icon}
      {label}
    </button>
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
        <img className="auth-logo" src="/site-icon.png" alt="" />
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
