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
  Trash2,
  UploadCloud,
  X,
  Zap,
} from "lucide-react";
import {
  api,
  AuthStatus,
  BookDetail,
  BrowseFilters,
  BrowseResult,
  DebugThreads,
  DownloadProgress,
  Job,
  Summary,
} from "./api";

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
  limitedScanActive: false,
  scanRunning: false,
  komgaAutoEnabled: false,
  limitedScanActiveThreshold: 300,
  libraryRoot: "",
  komgaUrl: "",
  autoScanEveryDays: 0,
  downloadConcurrency: 1,
  browserConcurrency: 2,
  imageDownloadWorkers: 4,
  readerEngine: "playwright",
  cpuPercent: 0,
};

export function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [summary, setSummary] = useState<Summary>(emptySummary);
  const [debugThreads, setDebugThreads] = useState<DebugThreads | null>(null);
  const [progress, setProgress] = useState<DownloadProgress[]>([]);
  const [details, setDetails] = useState<Record<number, BookDetail>>({});
  const [modalBookId, setModalBookId] = useState<number | null>(null);
  const [failedModalOpen, setFailedModalOpen] = useState(false);
  const [failedJobs, setFailedJobs] = useState<Job[]>([]);
  const [failedJobsLoading, setFailedJobsLoading] = useState(false);
  const [browseFilters, setBrowseFilters] = useState<BrowseFilters | null>(
    null,
  );
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
  const [browseMaxChapters, setBrowseMaxChapters] = useState(0);
  const [searchCollapsed, setSearchCollapsed] = useState(false);
  const [progressSearch, setProgressSearch] = useState("");
  const [progressFilter, setProgressFilter] = useState<
    "all" | "downloading" | "queued" | "done"
  >("all");
  const [hideExisting, setHideExisting] = useState(true);
  const [hideStringText, setHideStringText] = useState("");
  const [query, setQuery] = useState("");
  const [scanLimit, setScanLimit] = useState(300);
  const [intervalDays, setIntervalDays] = useState(0);
  const [downloadConcurrency, setDownloadConcurrency] = useState(1);
  const [browserConcurrency, setBrowserConcurrency] = useState(2);
  const [imageDownloadWorkers, setImageDownloadWorkers] = useState(4);
  const [readerEngine, setReaderEngine] = useState<"playwright" | "selenium">(
    "playwright",
  );
  const [komgaAutoEnabled, setKomgaAutoEnabled] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [loading, setLoading] = useState(false);
  const [scanLimitFocused, setScanLimitFocused] = useState(false);

  async function refresh() {
    const nextAuthStatus = await api.authStatus();
    setAuthStatus(nextAuthStatus);
    if (!nextAuthStatus.authenticated) {
      return;
    }
    const [nextSummary, nextProgress, nextThreads] = await Promise.all([
      api.summary(),
      api.progress(),
      api.debugThreads(),
    ]);
    setSummary(nextSummary);
    setProgress(nextProgress);
    setDebugThreads(nextThreads);
    setIntervalDays(nextSummary.autoScanEveryDays);
    setDownloadConcurrency(nextSummary.downloadConcurrency);
    setBrowserConcurrency(nextSummary.browserConcurrency);
    setImageDownloadWorkers(nextSummary.imageDownloadWorkers);
    setReaderEngine(nextSummary.readerEngine);
    setKomgaAutoEnabled(nextSummary.komgaAutoEnabled);
    if (!scanLimitFocused) {
      setScanLimit(nextSummary.limitedScanActiveThreshold);
    }
    if (!browseFilters) {
      setBrowseFilters(await api.asuraFilters());
    }
    if (modalBookId) {
      const detail = await api.bookDetail(modalBookId);
      setDetails((current) => ({ ...current, [modalBookId]: detail }));
    }
  }

  useEffect(() => {
    refresh().catch((error) => setStatus(error.message));
    const handle = window.setInterval(() => {
      refresh().catch((error) => setStatus(error.message));
    }, 5000);
    return () => window.clearInterval(handle);
  }, [modalBookId, browseFilters]);

  async function runAction(label: string, action: () => Promise<unknown>) {
    setLoading(true);
    setStatus(label);
    try {
      const result = await action();
      await refresh();
      if (
        result &&
        typeof result === "object" &&
        "reason" in result &&
        typeof result.reason === "string"
      ) {
        setStatus(`${label}: ${result.reason}`);
      } else {
        setStatus(`${label} started`);
      }
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
    await runAction("Settings update", () =>
      api.updateSettings(
        intervalDays,
        downloadConcurrency,
        browserConcurrency,
        imageDownloadWorkers,
        readerEngine,
        komgaAutoEnabled,
      ),
    );
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
      maxChapters: browseMaxChapters,
      limit: 24,
      offset,
    };
  }

  async function submitBrowseSearch(
    event?: FormEvent<HTMLFormElement>,
    offset = 0,
  ) {
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
    setBrowseGenres((current) =>
      current.includes(slug)
        ? current.filter((item) => item !== slug)
        : [...current, slug],
    );
  }

  const hiddenStrings = hideStringText
    .split(/\r?\n|,/)
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  const visibleBrowseResults = browseResults.filter((item) => {
    if (hideExisting && item.is_existing) return false;
    if (hiddenStrings.some((part) => item.title.toLowerCase().includes(part)))
      return false;
    return true;
  });

  async function openBook(bookId: number) {
    setModalBookId(bookId);
    if (!details[bookId]) {
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

  async function openFailedChapters() {
    if (summary.failedJobs === 0) return;
    setFailedModalOpen(true);
    setFailedJobsLoading(true);
    try {
      setFailedJobs(await api.failedJobs());
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setFailedJobsLoading(false);
    }
  }

  async function pauseOrResumeBook(
    item: DownloadProgress,
    detail?: BookDetail,
  ) {
    if (detail?.paused_downloads || item.paused > 0) {
      await runAction(`Resume downloads: ${item.manga_title}`, () =>
        api.resumeBookDownloads(item.manga_id),
      );
    } else {
      await runAction(`Pause downloads: ${item.manga_title}`, () =>
        api.pauseBookDownloads(item.manga_id),
      );
    }
    if (modalBookId === item.manga_id) {
      await refreshBook(item.manga_id);
    }
  }

  async function deleteQueuedDownloads() {
    const ok = window.confirm(
      "Remove all waiting downloads? Running, completed, and failed downloads are not removed.",
    );
    if (!ok) return;
    await runAction("Remove queued downloads", api.deleteQueuedDownloads);
  }

  async function deleteZeroPercentQueuedDownloads() {
    const ok = window.confirm(
      "Remove waiting downloads for books that are still at 0% and have not started? Running, completed, and failed downloads are not removed.",
    );
    if (!ok) return;
    await runAction(
      "Remove 0% queued downloads",
      api.deleteZeroPercentQueuedDownloads,
    );
  }

  function updateScanLimit(value: number) {
    setScanLimit(value);
    if (!Number.isFinite(value) || value < 1 || value > 5000) {
      return;
    }
    api
      .updateTopUpThreshold(value)
      .catch((error) =>
        setStatus(error instanceof Error ? error.message : String(error)),
      );
  }

  if (!authStatus) {
    return (
      <main className="app-shell">
        <div className="panel">Loading...</div>
      </main>
    );
  }

  if (!authStatus.authenticated) {
    return <AuthScreen authStatus={authStatus} onAuthenticated={refresh} />;
  }

  const modalItem = modalBookId
    ? progress.find((p) => p.manga_id === modalBookId)
    : null;

  const filteredProgress = progress.filter((item) => {
    if (
      progressSearch &&
      !item.manga_title.toLowerCase().includes(progressSearch.toLowerCase())
    )
      return false;
    if (progressFilter === "downloading" && item.running === 0) return false;
    if (progressFilter === "queued" && item.queued === 0) return false;
    if (
      progressFilter === "done" &&
      (item.queued > 0 || item.running > 0 || item.missing_count > 0)
    )
      return false;
    return true;
  });
  const queuedDownloadCount = progress.reduce(
    (sum, item) => sum + item.queued + item.paused,
    0,
  );
  const zeroPercentQueuedCount = progress.reduce((sum, item) => {
    if (
      item.queued + item.paused > 0 &&
      item.percent === 0 &&
      item.running === 0 &&
      item.done === 0 &&
      item.failed === 0
    ) {
      return sum + item.queued + item.paused;
    }
    return sum;
  }, 0);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <img className="site-mark" src="/site-icon2.png" alt="" />
          <div>
            <h1>Manga Crawler</h1>
            <p>{summary.libraryRoot || "Backend not connected"}</p>
            <p>Logged in as {authStatus.username}</p>
          </div>
        </div>
        <div className="topbar-actions">
          <button
            className="secondary"
            onClick={() => refresh()}
            disabled={loading}
            title="Refresh dashboard data now."
          >
            <RefreshCw size={17} />
            Refresh
          </button>
          <button
            className={summary.queuePaused ? "primary" : "secondary"}
            onClick={() =>
              runAction(
                summary.queuePaused ? "Queue resume" : "Queue pause",
                summary.queuePaused ? api.resumeQueue : api.pauseQueue,
              )
            }
            disabled={loading}
            title={
              summary.queuePaused
                ? "Resume all queued downloads."
                : "Pause all queued downloads after current running chapters finish."
            }
          >
            {summary.queuePaused ? <Play size={17} /> : <Pause size={17} />}
            {summary.queuePaused ? "Resume all" : "Pause all"}
          </button>
          <button
            className="secondary"
            onClick={() =>
              runAction("Retry failed downloads", api.retryFailedDownloads)
            }
            disabled={loading || summary.failedJobs === 0}
            title="Requeue failed chapter downloads and reset their attempt count."
          >
            Retry failed
          </button>
          <button
            className="secondary"
            onClick={() =>
              runAction("Logout", async () => {
                await api.logout();
                setAuthStatus(await api.authStatus());
              })
            }
            disabled={loading}
          >
            Logout
          </button>
        </div>
      </header>

      <section className="metrics">
        <Metric
          icon={<BookOpen />}
          label="Local books"
          value={summary.localBooks}
        />
        <Metric
          icon={<Download />}
          label="Local chapters"
          value={summary.localChapters}
        />
        <Metric
          icon={<Search />}
          label="Known Asura titles"
          value={summary.knownManga}
        />
        <Metric
          icon={<Clock />}
          label="Missing chapters"
          value={summary.missingChapters}
        />
        <Metric
          icon={<Activity />}
          label="Queued"
          value={summary.queuedJobs + summary.runningJobs}
        />
        <Metric icon={<Pause />} label="Paused" value={summary.pausedJobs} />
        <Metric
          icon={<Server />}
          label="Failed"
          value={summary.failedJobs}
          tone={summary.failedJobs ? "warn" : "normal"}
          onClick={openFailedChapters}
          disabled={summary.failedJobs === 0}
          title="Show failed chapter download details."
        />
        <Metric
          icon={<Activity />}
          label="CPU usage"
          value={Math.round(summary.cpuPercent)}
          suffix="%"
          tone={
            summary.cpuPercent >= 85
              ? "warn"
              : summary.cpuPercent >= 60
                ? "caution"
                : "normal"
          }
        />
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
              className="secondary danger"
              onClick={() => runAction("Stop scan", api.stopScan)}
              disabled={loading || (!summary.scanRunning && !summary.limitedScanActive)}
              title="Stop the active full scan or limited scan after its current network request finishes. Also disables limited scan continuation."
            >
              <X size={16} />
              Stop scan
            </button>
            <button
              className="secondary danger"
              onClick={() => runAction("Stop all scans", api.stopAllScans)}
              disabled={loading}
              title="Disable top-up and auto scan, request cancellation for every scan producer, and stop new scan enqueueing."
            >
              <X size={16} />
              Stop all scans
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
            <button
              className="secondary"
              onClick={() =>
                runAction("Import all libraries", api.importAllBooks)
              }
              disabled={loading}
              title="Create a Komga library for every folder in the books root that doesn't have one yet, then trigger a shallow scan. Runs in background."
            >
              Import all
            </button>
          </div>
          <div className="limited-scan">
            <label title="Keep topping up one next book while unfinished chapter downloads are below this number.">
              Find next book if active chapters below
              <input
                type="number"
                min={1}
                max={5000}
                value={scanLimit}
                onFocus={() => setScanLimitFocused(true)}
                onBlur={() => setScanLimitFocused(false)}
                onChange={(event) =>
                  updateScanLimit(Number(event.target.value))
                }
              />
              chapters
            </label>
            <button
              className="secondary"
              onClick={() =>
                runAction(`Top up below ${scanLimit} active chapters`, () =>
                  api.startTopUp(scanLimit),
                )
              }
              disabled={loading}
              title="Start limited top-up mode. It scans one next Asura book at a time until active chapter downloads reach this threshold."
            >
              Start top-up
            </button>
          </div>
          <form className="inline-form" onSubmit={submitSpecific}>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Manga title or Asura URL"
            />
            <button
              className="secondary"
              disabled={loading || !query.trim()}
              title="Find one Asura manga, compare it against local files, and enqueue missing chapters."
            >
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
                onChange={(event) =>
                  setIntervalDays(Number(event.target.value))
                }
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
                onChange={(event) =>
                  setDownloadConcurrency(Number(event.target.value))
                }
              />
            </label>
            <label title="Limit simultaneous rendered reader pages. Lower values reduce browser CPU.">
              Browser pages
              <input
                type="number"
                min={1}
                max={4}
                value={browserConcurrency}
                onChange={(event) =>
                  setBrowserConcurrency(Number(event.target.value))
                }
              />
            </label>
            <label title="Limit HTTP page image downloads per chapter after image URLs are extracted.">
              Image workers
              <input
                type="number"
                min={1}
                max={8}
                value={imageDownloadWorkers}
                onChange={(event) =>
                  setImageDownloadWorkers(Number(event.target.value))
                }
              />
            </label>
            <label title="Playwright uses one shared browser process. Selenium is available as fallback.">
              Reader engine
              <select
                value={readerEngine}
                onChange={(event) =>
                  setReaderEngine(event.target.value as "playwright" | "selenium")
                }
              >
                <option value="playwright">Playwright</option>
                <option value="selenium">Selenium</option>
              </select>
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={komgaAutoEnabled}
                onChange={(event) =>
                  setKomgaAutoEnabled(event.target.checked)
                }
              />
              Auto Komga import/scan after downloads
            </label>
            <button className="secondary" disabled={loading}>
              Save
            </button>
          </form>
          <p className="muted">
            Auto scan 0 disables scheduling. Browser pages controls CPU-heavy
            reader rendering; image workers controls HTTP transfer parallelism.
            Komga automation is{" "}
            {summary.komgaAutoEnabled ? "enabled" : "disabled"}. Last scan:{" "}
            {summary.lastScanAt
              ? new Date(summary.lastScanAt).toLocaleString()
              : "never"}
          </p>
        </div>
      </section>

      {debugThreads && (
        <ThreadPanel
          debugThreads={debugThreads}
          loading={loading}
          onStopThread={(threadIdent) =>
            runAction(`Stop thread ${threadIdent}`, () =>
              api.stopThread(threadIdent),
            )
          }
        />
      )}

      {/* Collapsible Search Section */}
      <section className="panel search-panel">
        <button
          type="button"
          className="panel-collapse-toggle"
          onClick={() => setSearchCollapsed((v) => !v)}
          title={
            searchCollapsed ? "Expand Asura Search" : "Collapse Asura Search"
          }
        >
          <Search size={18} />
          Asura Search
          {browseResults.length > 0 && !searchCollapsed && (
            <span
              style={{
                color: "#9aa5b5",
                fontWeight: 400,
                fontSize: 13,
                marginLeft: 4,
              }}
            >
              — {visibleBrowseResults.length} results
            </span>
          )}
          <ChevronDown
            size={16}
            className={`collapse-chevron${searchCollapsed ? "" : " open"}`}
          />
        </button>

        {!searchCollapsed && (
          <div className="search-panel-body">
            <form
              className="browse-form"
              onSubmit={(event) => submitBrowseSearch(event, 0)}
            >
              <input
                value={browseSearch}
                onChange={(event) => setBrowseSearch(event.target.value)}
                placeholder="Search Asura titles"
                title="Search Asura by title."
              />
              <select
                value={browseStatus}
                onChange={(event) => setBrowseStatus(event.target.value)}
                title="Filter by Asura status."
              >
                {(
                  browseFilters?.statuses ?? [
                    "all",
                    "ongoing",
                    "completed",
                    "hiatus",
                    "dropped",
                    "axed",
                  ]
                ).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <select
                value={browseType}
                onChange={(event) => setBrowseType(event.target.value)}
                title="Filter by series type."
              >
                {(
                  browseFilters?.types ?? ["all", "manhwa", "manhua", "manga"]
                ).map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <select
                value={browseSort}
                onChange={(event) => setBrowseSort(event.target.value)}
                title="Sort Asura results."
              >
                {(
                  browseFilters?.sorts ?? [
                    "latest",
                    "popular",
                    "rating",
                    "title",
                    "chapters",
                  ]
                ).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <select
                value={browseOrder}
                onChange={(event) => setBrowseOrder(event.target.value)}
                title="Sort direction."
              >
                <option value="desc">desc</option>
                <option value="asc">asc</option>
              </select>
              <button
                className="primary"
                disabled={browseLoading}
                title="Search Asura using the selected filters."
              >
                Search
              </button>
            </form>

            {/* Extra filters row */}
            <div className="browse-filters-row">
              <label title="Filter by author name.">
                Author
                <input
                  value={browseAuthor}
                  onChange={(event) => setBrowseAuthor(event.target.value)}
                  placeholder="Any author"
                  list="author-options"
                />
                <datalist id="author-options">
                  {(browseFilters?.authors ?? []).map((a) => (
                    <option key={a} value={a} />
                  ))}
                </datalist>
              </label>
              <label title="Filter by artist name.">
                Artist
                <input
                  value={browseArtist}
                  onChange={(event) => setBrowseArtist(event.target.value)}
                  placeholder="Any artist"
                  list="artist-options"
                />
                <datalist id="artist-options">
                  {(browseFilters?.artists ?? []).map((a) => (
                    <option key={a} value={a} />
                  ))}
                </datalist>
              </label>
              <label title="Show only series with at least this many chapters.">
                Min episodes
                <input
                  type="number"
                  min={0}
                  value={browseMinChapters}
                  onChange={(event) =>
                    setBrowseMinChapters(Number(event.target.value))
                  }
                  placeholder="0 = any"
                />
              </label>
              <label title="Show only series with at most this many chapters. 0 = no limit.">
                Max episodes
                <input
                  type="number"
                  min={0}
                  value={browseMaxChapters}
                  onChange={(event) =>
                    setBrowseMaxChapters(Number(event.target.value))
                  }
                  placeholder="0 = no limit"
                />
              </label>
            </div>

            <div className="filter-options">
              <label title="Hide books already found in your local Komga folder.">
                <input
                  type="checkbox"
                  checked={hideExisting}
                  onChange={(event) => setHideExisting(event.target.checked)}
                />
                Hide existing books
              </label>
              <label
                className="hide-strings"
                title="Comma or newline separated strings. Any matching title is hidden from the results."
              >
                Hide titles containing
                <textarea
                  value={hideStringText}
                  onChange={(event) => setHideStringText(event.target.value)}
                  placeholder="academy, regression, necromancer"
                />
              </label>
            </div>

            <div className="genre-strip">
              {(browseFilters?.genres ?? []).map((genre) => (
                <button
                  key={genre.slug}
                  type="button"
                  className={
                    browseGenres.includes(genre.slug) ? "chip selected" : "chip"
                  }
                  onClick={() => toggleGenre(genre.slug)}
                  title={`Toggle ${genre.name} genre filter.`}
                >
                  {genre.name}
                </button>
              ))}
            </div>

            <div className="search-results-header">
              <span>
                Showing {visibleBrowseResults.length} of {browseResults.length}{" "}
                loaded results
                {browseTotal
                  ? `, ${browseTotal.toLocaleString()} total from Asura`
                  : ""}
              </span>
              <div className="button-row">
                <button
                  className="primary"
                  disabled={
                    browseLoading || loading || browseResults.length === 0
                  }
                  onClick={() =>
                    runAction("Priority scan", () =>
                      api.priorityScan(browsePayload(browseOffset)),
                    )
                  }
                  title="Scan only the currently loaded Asura result page and place its missing chapters at the front of the download queue. Runs in background."
                >
                  Priority scan page
                </button>
                <button
                  className="secondary"
                  disabled={browseLoading || browseOffset === 0}
                  onClick={() =>
                    submitBrowseSearch(
                      undefined,
                      Math.max(0, browseOffset - 24),
                    )
                  }
                  title="Load previous Asura result page."
                >
                  Previous
                </button>
                <button
                  className="secondary"
                  disabled={browseLoading || browseOffset + 24 >= browseTotal}
                  onClick={() =>
                    submitBrowseSearch(undefined, browseOffset + 24)
                  }
                  title="Load next Asura result page."
                >
                  Next
                </button>
              </div>
            </div>

            <div className="browse-results">
              {visibleBrowseResults.map((item) => (
                <BrowseResultRow
                  key={item.id}
                  item={item}
                  loading={loading || browseLoading}
                  onAdd={() =>
                    runAction(`Add book: ${item.title}`, () =>
                      api.specificPriorityScan(item.url),
                    )
                  }
                />
              ))}
              {!visibleBrowseResults.length && (
                <p className="empty">No visible search results yet.</p>
              )}
            </div>
          </div>
        )}
      </section>

      {/* Total download progress bar */}
      <TotalProgressBar progress={progress} />

      <section className="panel progress-panel">
        <div className="panel-title">
          <Info size={18} />
          Books and Download Progress
        </div>
        <div className="progress-controls">
          <input
            className="progress-search"
            value={progressSearch}
            onChange={(e) => setProgressSearch(e.target.value)}
            placeholder="Search books..."
          />
          <div className="progress-filter-chips">
            {(["all", "downloading", "queued", "done"] as const).map((f) => (
              <button
                key={f}
                type="button"
                className={progressFilter === f ? "chip selected" : "chip"}
                onClick={() => setProgressFilter(f)}
              >
                {f}
              </button>
            ))}
          </div>
          <div className="progress-queue-actions">
            <button
              type="button"
              className="secondary danger"
              onClick={deleteQueuedDownloads}
              disabled={loading || queuedDownloadCount === 0}
              title="Remove all waiting download jobs. Running, completed, and failed downloads stay untouched."
            >
              <Trash2 size={15} />
              Clear queued
            </button>
            <button
              type="button"
              className="secondary danger"
              onClick={deleteZeroPercentQueuedDownloads}
              disabled={loading || zeroPercentQueuedCount === 0}
              title="Remove waiting download jobs only for books still at 0% with no started download history."
            >
              <Trash2 size={15} />
              Clear 0%
            </button>
          </div>
          <span className="progress-count">
            {filteredProgress.length} / {progress.length}
          </span>
        </div>
        {filteredProgress.length ? (
          <div className="progress-list">
            {filteredProgress.map((item) => (
              <ProgressRow
                key={item.manga_id}
                item={item}
                active={modalBookId === item.manga_id}
                loading={loading}
                onOpen={() => openBook(item.manga_id)}
              />
            ))}
          </div>
        ) : (
          <p className="empty">
            {progress.length
              ? "No books match the current filter."
              : "No tracked books yet. Run a scan to populate progress."}
          </p>
        )}
      </section>

      {/* Book detail modal */}
      {modalBookId && modalItem && (
        <BookDetailModal
          item={modalItem}
          detail={details[modalBookId]}
          loading={loading}
          onClose={() => setModalBookId(null)}
          onRefresh={() =>
            runAction(`Refresh: ${modalItem.manga_title}`, () =>
              refreshBook(modalBookId),
            )
          }
          onDownloadNow={() =>
            runAction(`Download now: ${modalItem.manga_title}`, () =>
              api.downloadNow(modalBookId),
            )
          }
          onPause={() => pauseOrResumeBook(modalItem, details[modalBookId])}
          onQuickScan={() =>
            runAction(`Fast Komga scan: ${modalItem.manga_title}`, () =>
              api.quickScanBook(modalBookId),
            )
          }
          onImport={() =>
            runAction(`Komga import: ${modalItem.manga_title}`, () =>
              api.importBook(modalBookId),
            )
          }
          onRetryFailed={() =>
            runAction(`Retry failed: ${modalItem.manga_title}`, () =>
              api.retryFailedBookDownloads(modalBookId),
            )
          }
          onSpecificScan={() =>
            runAction(`Quick scan: ${modalItem.manga_title}`, () =>
              api.specificScan(modalItem.url || modalItem.manga_title),
            )
          }
        />
      )}

      {failedModalOpen && (
        <FailedChaptersModal
          jobs={failedJobs}
          loading={failedJobsLoading}
          onClose={() => setFailedModalOpen(false)}
        />
      )}
    </main>
  );
}

function TotalProgressBar({ progress }: { progress: DownloadProgress[] }) {
  const totalDone = progress.reduce((sum, p) => sum + p.done, 0);
  const totalInQueue = progress.reduce(
    (sum, p) => sum + p.queued + p.running,
    0,
  );
  const totalPaused = progress.reduce((sum, p) => sum + p.paused, 0);
  const totalFailed = progress.reduce((sum, p) => sum + p.failed, 0);
  const totalActive = totalInQueue + totalPaused + totalFailed;
  const totalItems = totalDone + totalActive;
  const percent =
    totalItems > 0 ? Math.round((totalDone / totalItems) * 100) : 0;

  if (!totalItems) return null;

  const activeLabel = [
    totalInQueue > 0 && `${totalInQueue} in queue`,
    totalPaused > 0 && `${totalPaused} paused`,
    totalFailed > 0 && `${totalFailed} failed`,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="panel total-progress-panel">
      <div className="total-progress-header">
        <span>
          <Download size={14} /> Overall progress
        </span>
        <span>
          {totalDone.toLocaleString()} / {totalItems.toLocaleString()} episodes
        </span>
        <span className="total-percent">{percent}%</span>
        {totalActive > 0 && (
          <span className="total-active">{activeLabel}</span>
        )}
      </div>
      <div className="progress-track">
        <div
          className="progress-fill"
          style={{ width: `${Math.min(100, percent)}%` }}
        />
      </div>
    </div>
  );
}

function ThreadPanel({
  debugThreads,
  loading,
  onStopThread,
}: {
  debugThreads: DebugThreads;
  loading: boolean;
  onStopThread: (threadIdent: number) => void;
}) {
  const activeWorkers = debugThreads.downloadQueue.workers.filter(
    (worker) => worker.alive,
  );
  const scanThreads = debugThreads.threads.filter((thread) =>
    thread.name !== "scan-scheduler" && /scan|import/i.test(thread.name),
  );

  return (
    <section className="panel thread-panel">
      <div className="panel-title">
        <Activity size={18} />
        Active Threads
      </div>
      <div className="thread-grid">
        <DetailStat
          label="Scan stop requested"
          value={debugThreads.scanStopRequested ? "Yes" : "No"}
        />
        <DetailStat
          label="Scan job"
          value={debugThreads.scheduler.scanRunning ? "Running" : "Idle"}
        />
        <DetailStat
          label="Scheduler service"
          value={debugThreads.scheduler.thread.alive ? "Alive" : "Stopped"}
        />
        <DetailStat
          label="Top-up"
          value={debugThreads.settings.limitedScanActive ? "Active" : "Off"}
        />
        <DetailStat
          label="Auto scan days"
          value={`${debugThreads.settings.autoScanEveryDays}`}
        />
      </div>
      {debugThreads.scheduler.currentScan && (
        <div className="thread-row">
          <strong>Current scan</strong>
          <span>{JSON.stringify(debugThreads.scheduler.currentScan)}</span>
        </div>
      )}
      <div className="thread-list">
        {activeWorkers.map((worker) => (
          <div className="thread-row" key={`${worker.name}-${worker.ident}`}>
            <div>
              <strong>{worker.name}</strong>
              <span>
                {worker.job
                  ? JSON.stringify(worker.job)
                  : "Idle download worker"}
              </span>
            </div>
            <button
              type="button"
              className="mini-button danger"
              disabled={loading || worker.ident === null}
              onClick={() => worker.ident !== null && onStopThread(worker.ident)}
              title="Ask this download worker to exit after its current chapter or idle loop."
            >
              Stop
            </button>
          </div>
        ))}
        {scanThreads.map((thread) => {
          const stoppable = thread.ident !== null && /scan|scheduler/i.test(thread.name);
          return (
            <div className="thread-row" key={`${thread.name}-${thread.ident}`}>
              <div>
                <strong>{thread.name}</strong>
                <span>{thread.alive ? "Alive" : "Stopped"}</span>
              </div>
              {stoppable && (
                <button
                  type="button"
                  className="mini-button danger"
                  disabled={loading}
                  onClick={() => onStopThread(thread.ident as number)}
                  title="Request cancellation for this scan thread. It exits at the next cancellation checkpoint."
                >
                  Stop
                </button>
              )}
            </div>
          );
        })}
        {!activeWorkers.length && !scanThreads.length && (
          <p className="empty">No active scan or download worker threads.</p>
        )}
      </div>
    </section>
  );
}

function ProgressRow({
  item,
  active,
  loading,
  onOpen,
}: {
  item: DownloadProgress;
  active: boolean;
  loading: boolean;
  onOpen: () => void;
}) {
  const episodeTotal = item.remote_chapter_count || item.total || 0;
  const downloaded = item.available_count ?? item.done;

  return (
    <article className={`progress-row${active ? " active" : ""}`}>
      <button
        className="progress-main"
        onClick={onOpen}
        disabled={loading}
        title="Open details popup."
      >
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
        <div
          className="progress-track"
          aria-label={`${item.percent}% complete`}
        >
          <div
            className="progress-fill"
            style={{ width: `${Math.min(100, item.percent)}%` }}
          />
        </div>
        <div className="progress-meta">
          <span>{item.percent}%</span>
          <span>{item.queued} queued</span>
          {item.paused > 0 && <span>{item.paused} paused</span>}
          {item.failed > 0 && (
            <span style={{ color: "#fca5a5" }}>{item.failed} failed</span>
          )}
        </div>
        <ChevronDown className="progress-chevron" size={18} />
      </button>
    </article>
  );
}

function BookDetailModal({
  item,
  detail,
  loading,
  onClose,
  onRefresh,
  onDownloadNow,
  onPause,
  onQuickScan,
  onImport,
  onRetryFailed,
  onSpecificScan,
}: {
  item: DownloadProgress;
  detail?: BookDetail;
  loading: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onDownloadNow: () => void;
  onPause: () => void;
  onQuickScan: () => void;
  onImport: () => void;
  onRetryFailed: () => void;
  onSpecificScan: () => void;
}) {
  const paused = Boolean(detail?.paused_downloads || item.paused > 0);
  const localChapters = detail?.local_chapters ?? [];
  const newlyDownloaded =
    detail?.chapters.filter((ch) => ch.is_downloaded && ch.file_path) ?? [];
  // Compute missing dynamically from remote - available (available already caps at remote)
  const computedMissing = detail
    ? Math.max(
        0,
        (detail.remote_chapter_count ?? 0) - (detail.downloaded_count ?? 0),
      )
    : item.missing_count;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>{item.manga_title}</h2>
            <p>{item.local_folder ?? "Not in local library yet"}</p>
          </div>
          <button
            className="secondary"
            onClick={onClose}
            title="Close this panel."
          >
            <X size={16} /> Close
          </button>
        </div>

        <div className="book-action-bar">
          <IconButton
            icon={<RefreshCw size={16} />}
            label="Refresh"
            title="Refresh this book's details."
            onClick={onRefresh}
            disabled={loading}
          />
          <IconButton
            icon={<Download size={16} />}
            label="Download now"
            title="Pause all other downloads and download this book first."
            onClick={onDownloadNow}
            disabled={loading}
          />
          <IconButton
            icon={paused ? <Play size={16} /> : <Pause size={16} />}
            label={paused ? "Resume" : "Pause"}
            title="Pause or resume queued downloads for this book."
            onClick={onPause}
            disabled={loading}
          />
          <IconButton
            icon={<Search size={16} />}
            label="Quick scan"
            title="Scan this manga on Asura and enqueue any newly missing chapters."
            onClick={onSpecificScan}
            disabled={loading}
          />
          <IconButton
            icon={<RefreshCw size={16} />}
            label="Retry failed"
            title="Requeue failed chapter downloads for this book."
            onClick={onRetryFailed}
            disabled={loading || item.failed === 0}
          />
          <IconButton
            icon={<UploadCloud size={16} />}
            label="Import"
            title="Create or find this book's Komga library without forcing a scan."
            onClick={onImport}
            disabled={loading}
          />
          <IconButton
            icon={<Zap size={16} />}
            label="Fast scan"
            title="Run Komga quick scan for this book with deep=false."
            onClick={onQuickScan}
            disabled={loading}
          />
        </div>

        <div className="episode-summary">
          <DetailStat label="Status" value={detail?.status ?? "unknown"} />
          <DetailStat
            label="On disk"
            value={`${detail?.local_chapter_count ?? item.existing_downloaded_count} episodes`}
          />
          <DetailStat
            label="Asura total"
            value={`${detail?.remote_chapter_count ?? item.remote_chapter_count} episodes`}
          />
          <DetailStat label="Missing" value={`${computedMissing} episodes`} />
          <DetailStat
            label="Downloaded by app"
            value={`${detail?.newly_downloaded_count ?? item.newly_downloaded_count} episodes`}
          />
          <DetailStat label="Queued" value={`${item.queued}`} />
          <DetailStat
            label="Storage path"
            value={
              detail?.local_folder ?? item.local_folder ?? "Not created yet"
            }
          />
          <DetailStat
            label="Komga import"
            value={
              detail?.komga_imported_at
                ? new Date(detail.komga_imported_at).toLocaleString()
                : "Not recorded"
            }
          />
          <DetailStat
            label="Fast library scan"
            value={
              detail?.komga_scanned_at
                ? new Date(detail.komga_scanned_at).toLocaleString()
                : "Not recorded"
            }
          />
          <DetailStat
            label="Komga error"
            value={detail?.komga_last_error ?? "None"}
          />
        </div>

        <div className="episode-list">
          {localChapters.map((chapter) => (
            <div key={`local-${chapter}`} className="episode-row existing">
              <strong>Chapter {chapter}</strong>
              <span>Pre-existing on disk</span>
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
    </div>
  );
}

function FailedChaptersModal({
  jobs,
  loading,
  onClose,
}: {
  jobs: Job[];
  loading: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel failed-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>Failed chapters</h2>
            <p>{jobs.length.toLocaleString()} failed download jobs</p>
          </div>
          <button
            className="secondary"
            onClick={onClose}
            title="Close failed chapter details."
          >
            <X size={16} /> Close
          </button>
        </div>

        <div className="failed-chapter-list">
          {loading && <p className="empty">Loading failed chapters...</p>}
          {!loading &&
            jobs.map((job) => (
              <div className="failed-chapter-row" key={job.id}>
                <div>
                  <strong>{job.manga_title ?? "Unknown book"}</strong>
                  <span>Chapter {job.chapter_key ?? job.chapter_label ?? "unknown"}</span>
                </div>
                <p>{job.error || "No failure reason recorded."}</p>
              </div>
            ))}
          {!loading && jobs.length === 0 && (
            <p className="empty">No failed chapters found.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function BrowseResultRow({
  item,
  loading,
  onAdd,
}: {
  item: BrowseResult;
  loading: boolean;
  onAdd: () => void;
}) {
  return (
    <div className="browse-result-row">
      {item.cover_url ? (
        <img src={item.cover_url} alt="" loading="lazy" />
      ) : (
        <div className="cover-placeholder">
          <BookOpen size={20} />
        </div>
      )}
      <div>
        <a href={item.url} target="_blank" rel="noreferrer">
          {item.title}
        </a>
        <span>
          {[item.status, item.type, `${item.chapter_count} episodes`]
            .filter(Boolean)
            .join(" · ")}
        </span>
        <small>
          {item.genres.map((genre) => genre.name).join(", ") ||
            "No genres listed"}
        </small>
        {item.local_folder && <small>{item.local_folder}</small>}
      </div>
      <div className="browse-counts">
        <DetailStat label="On disk" value={`${item.local_chapter_count}`} />
        <DetailStat label="Asura" value={`${item.chapter_count}`} />
        <DetailStat label="Missing" value={`${item.missing_count}`} />
      </div>
      <button
        className="primary"
        onClick={onAdd}
        disabled={loading}
        title="Add this book by scanning it and queueing missing chapters."
      >
        Add
      </button>
    </div>
  );
}

function IconButton({
  icon,
  label,
  title,
  onClick,
  disabled,
}: {
  icon: JSX.Element;
  label: string;
  title: string;
  onClick: () => void;
  disabled: boolean;
}) {
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

function AuthScreen({
  authStatus,
  onAuthenticated,
}: {
  authStatus: AuthStatus;
  onAuthenticated: () => Promise<void>;
}) {
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
        <img className="auth-logo" src="/site-icon2.png" alt="" />
        <div className="auth-icon">
          <Lock size={22} />
        </div>
        <h1>{mode === "register" ? "Create owner account" : "Log in"}</h1>
        <p>
          {mode === "register"
            ? "First startup requires one owner account. Registration closes after this user is created."
            : "Registration is closed. Use the owner account to continue."}
        </p>
        <label>
          Username
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
          />
        </label>
        <label>
          Password
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete={
              mode === "register" ? "new-password" : "current-password"
            }
          />
        </label>
        {error && <div className="auth-error">{error}</div>}
        <button
          className="primary"
          disabled={loading || !username.trim() || !password}
        >
          {mode === "register" ? "Register owner" : "Log in"}
        </button>
      </form>
    </main>
  );
}

function Metric({
  icon,
  label,
  value,
  suffix,
  tone = "normal",
  onClick,
  disabled = false,
  title,
}: {
  icon: JSX.Element;
  label: string;
  value: number;
  suffix?: string;
  tone?: "normal" | "caution" | "warn";
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
}) {
  const content = (
    <>
      <div className="metric-icon">{icon}</div>
      <span>{label}</span>
      <strong>{value.toLocaleString()}{suffix}</strong>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className={`metric metric-button ${tone}`}
        onClick={onClick}
        disabled={disabled}
        title={title}
      >
        {content}
      </button>
    );
  }

  return (
    <div className={`metric ${tone}`}>
      {content}
    </div>
  );
}
