import { useEffect, useState } from "react";
import {
  ChevronDown,
  Download,
  Pause,
  Play,
  RefreshCw,
  Search,
  Trash2,
  UploadCloud,
  X,
  Zap,
} from "lucide-react";
import { api, BookDetail, DownloadProgress, Job } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";

type FilterType = "all" | "downloading" | "queued";

export function DownloadsPage({ summary, progress, loading, runAction }: SharedProps) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterType>("all");
  const [modalId, setModalId] = useState<number | null>(null);
  const [details, setDetails] = useState<Record<number, BookDetail>>({});
  const [failedOpen, setFailedOpen] = useState(false);
  const [failedJobs, setFailedJobs] = useState<Job[]>([]);
  const [failedLoading, setFailedLoading] = useState(false);

  // Poll modal book detail while open
  useEffect(() => {
    if (!modalId) return;
    api.bookDetail(modalId)
      .then((d) => setDetails((c) => ({ ...c, [modalId]: d })))
      .catch(() => {});
    const h = setInterval(() => {
      api.bookDetail(modalId)
        .then((d) => setDetails((c) => ({ ...c, [modalId]: d })))
        .catch(() => {});
    }, 5000);
    return () => clearInterval(h);
  }, [modalId]);

  async function openBook(id: number) {
    setModalId(id);
    if (!details[id]) {
      try {
        const d = await api.bookDetail(id);
        setDetails((c) => ({ ...c, [id]: d }));
      } catch (_) {}
    }
  }

  async function refreshBook(id: number) {
    const d = await api.bookDetail(id);
    setDetails((c) => ({ ...c, [id]: d }));
  }

  async function pauseOrResume(item: DownloadProgress) {
    const detail = details[item.manga_id];
    if (detail?.paused_downloads || item.paused > 0) {
      await runAction(`Resume: ${item.manga_title}`, () =>
        api.resumeBookDownloads(item.manga_id),
      );
    } else {
      await runAction(`Pause: ${item.manga_title}`, () =>
        api.pauseBookDownloads(item.manga_id),
      );
    }
    if (modalId === item.manga_id) await refreshBook(item.manga_id);
  }

  async function openFailed() {
    if (summary.failedJobs === 0) return;
    setFailedOpen(true);
    setFailedLoading(true);
    try {
      setFailedJobs(await api.failedJobs());
    } catch (_) {}
    finally { setFailedLoading(false); }
  }

  async function clearQueued() {
    if (!window.confirm("Remove all waiting downloads? Running, completed, and failed downloads are not removed.")) return;
    await runAction("Clear queued downloads", api.deleteQueuedDownloads);
  }

  async function clearZeroPercent() {
    if (!window.confirm("Remove waiting downloads for books still at 0%? Running, completed, and failed downloads stay.")) return;
    await runAction("Clear 0% queued downloads", api.deleteZeroPercentQueuedDownloads);
  }

  const queuedCount = progress.reduce((s, p) => s + p.queued + p.paused, 0);
  const zeroCount   = progress.reduce((s, p) => {
    if (p.queued + p.paused > 0 && p.percent === 0 && p.running === 0 && p.done === 0 && p.failed === 0)
      return s + p.queued + p.paused;
    return s;
  }, 0);

  const filtered = progress.filter((p) => {
    // Always hide books with no active work
    if (p.running === 0 && p.queued === 0 && p.paused === 0 && p.failed === 0) return false;
    if (search && !p.manga_title.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "downloading" && p.running === 0) return false;
    if (filter === "queued"      && p.queued === 0)  return false;
    return true;
  });

  const modalItem = modalId ? progress.find((p) => p.manga_id === modalId) ?? null : null;

  return (
    <>
      <div className="page-header">
        <div className="page-title-row">
          <h2>Downloads</h2>
          {progress.length > 0 && (
            <span className="tag tag-purple">{progress.length} books tracked</span>
          )}
        </div>
        <div className="page-actions">
          {summary.failedJobs > 0 && (
            <button className="btn-ghost btn-sm danger" onClick={openFailed}>
              {summary.failedJobs} failed — view
            </button>
          )}
          <button
            className="btn-ghost btn-sm"
            onClick={() => runAction("Retry failed downloads", api.retryFailedDownloads)}
            disabled={loading || summary.failedJobs === 0}
          >
            <RefreshCw size={13} /> Retry failed
          </button>
        </div>
      </div>

      {/* Controls */}
      <div className="dl-controls">
        <input
          className="search-input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search books…"
        />
        <div className="filter-chips">
          {(["all", "downloading", "queued"] as FilterType[]).map((f) => (
            <button
              key={f}
              type="button"
              className={`chip${filter === f ? " on" : ""}`}
              onClick={() => setFilter(f)}
            >
              {f}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            className="btn-ghost btn-sm danger"
            onClick={clearQueued}
            disabled={loading || queuedCount === 0}
            title="Remove all waiting download jobs."
          >
            <Trash2 size={12} /> Clear queued
          </button>
          <button
            className="btn-ghost btn-sm danger"
            onClick={clearZeroPercent}
            disabled={loading || zeroCount === 0}
            title="Remove waiting downloads for books still at 0%."
          >
            <Trash2 size={12} /> Clear 0%
          </button>
        </div>
        <span className="dl-count">{filtered.length} / {progress.length}</span>
      </div>

      {/* List */}
      {filtered.length > 0 ? (
        <div className="dl-list">
          {filtered.map((item) => (
            <ProgressItem
              key={item.manga_id}
              item={item}
              active={modalId === item.manga_id}
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

      {/* Book detail modal */}
      {modalId && modalItem && (
        <BookDetailModal
          item={modalItem}
          detail={details[modalId]}
          loading={loading}
          onClose={() => setModalId(null)}
          onRefresh={() =>
            runAction(`Refresh: ${modalItem.manga_title}`, () => refreshBook(modalId))
          }
          onDownloadNow={() =>
            runAction(`Download now: ${modalItem.manga_title}`, () =>
              api.downloadNow(modalId),
            )
          }
          onPause={() => pauseOrResume(modalItem)}
          onQuickScan={() =>
            runAction(`Fast Komga scan: ${modalItem.manga_title}`, () =>
              api.quickScanBook(modalId),
            )
          }
          onImport={() =>
            runAction(`Komga import: ${modalItem.manga_title}`, () =>
              api.importBook(modalId),
            )
          }
          onRetryFailed={() =>
            runAction(`Retry failed: ${modalItem.manga_title}`, () =>
              api.retryFailedBookDownloads(modalId),
            )
          }
          onSpecificScan={() =>
            runAction(`Quick scan: ${modalItem.manga_title}`, () =>
              api.specificScan(modalItem.url || modalItem.manga_title),
            )
          }
        />
      )}

      {/* Failed chapters modal */}
      {failedOpen && (
        <FailedModal
          jobs={failedJobs}
          loading={failedLoading}
          onClose={() => setFailedOpen(false)}
        />
      )}
    </>
  );
}

/* ── Progress item ────────────────────────────────────────────── */
function ProgressItem({
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
  const downloaded   = item.available_count ?? item.done;

  return (
    <article className={`pi${active ? " pi-active" : ""}${loading ? " pi-disabled" : ""}`}>
      <button
        className="pi-btn"
        onClick={onOpen}
        disabled={loading}
        title="Open details."
      >
        <div className="pi-top">
          <div>
            <div className="pi-title">{item.manga_title}</div>
            <div className="pi-folder">{item.local_folder ?? "Not in local library yet"}</div>
          </div>
          <span className="pi-count">
            {downloaded}/{episodeTotal} ep
            {item.running ? `, ${item.running} running` : ""}
          </span>
        </div>
        <div className="pi-track track">
          <div className="track-fill" style={{ width: `${Math.min(100, item.percent)}%` }} />
        </div>
        <div className="pi-meta">
          <span>{item.percent}%</span>
          <span>{item.queued} queued</span>
          {item.paused > 0 && <span>{item.paused} paused</span>}
          {item.failed > 0 && <span className="warn">{item.failed} failed</span>}
        </div>
        <ChevronDown className="pi-arrow" size={16} />
      </button>
    </article>
  );
}

/* ── Book detail modal ────────────────────────────────────────── */
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
  const newlyDownloaded = detail?.chapters.filter((ch) => ch.is_downloaded && ch.file_path) ?? [];
  const computedMissing = detail
    ? Math.max(0, (detail.remote_chapter_count ?? 0) - (detail.downloaded_count ?? 0))
    : item.missing_count;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>{item.manga_title}</h2>
            <p>{item.local_folder ?? "Not in local library yet"}</p>
          </div>
          <button className="btn-ghost btn-sm" onClick={onClose}>
            <X size={14} /> Close
          </button>
        </div>

        <div className="modal-actions">
          <MiniBtn icon={<RefreshCw size={13} />} label="Refresh"      onClick={onRefresh}      disabled={loading} />
          <MiniBtn icon={<Download size={13} />}  label="Download now" onClick={onDownloadNow}  disabled={loading} />
          <MiniBtn icon={paused ? <Play size={13} /> : <Pause size={13} />} label={paused ? "Resume" : "Pause"} onClick={onPause} disabled={loading} />
          <MiniBtn icon={<Search size={13} />}    label="Quick scan"   onClick={onSpecificScan} disabled={loading} />
          <MiniBtn icon={<RefreshCw size={13} />} label="Retry failed" onClick={onRetryFailed}  disabled={loading || item.failed === 0} />
          <MiniBtn icon={<UploadCloud size={13} />} label="Import"     onClick={onImport}       disabled={loading} />
          <MiniBtn icon={<Zap size={13} />}       label="Fast scan"    onClick={onQuickScan}    disabled={loading} />
        </div>

        <div className="ep-stats">
          <StatCard label="Status"        value={detail?.status ?? "unknown"} />
          <StatCard label="On disk"       value={`${detail?.local_chapter_count ?? item.existing_downloaded_count} ep`} />
          <StatCard label="Asura total"   value={`${detail?.remote_chapter_count ?? item.remote_chapter_count} ep`} />
          <StatCard label="Missing"       value={`${computedMissing} ep`} />
          <StatCard label="Downloaded"    value={`${detail?.newly_downloaded_count ?? item.newly_downloaded_count} ep`} />
          <StatCard label="Queued"        value={`${item.queued}`} />
          <StatCard label="Storage path"  value={detail?.local_folder ?? item.local_folder ?? "Not created yet"} />
          <StatCard label="Komga import"  value={detail?.komga_imported_at ? new Date(detail.komga_imported_at).toLocaleString() : "Not recorded"} />
          <StatCard label="Fast scan"     value={detail?.komga_scanned_at ? new Date(detail.komga_scanned_at).toLocaleString() : "Not recorded"} />
          <StatCard label="Komga error"   value={detail?.komga_last_error ?? "None"} />
        </div>

        <div className="ep-list">
          {localChapters.map((ch) => (
            <div key={`local-${ch}`} className="ep-row">
              <strong>Chapter {ch}</strong>
              <span>Pre-existing on disk</span>
            </div>
          ))}
          {newlyDownloaded.map((ch) => (
            <div key={`new-${ch.id}`} className="ep-row new">
              <strong>{ch.label}</strong>
              <span>{ch.file_path}</span>
            </div>
          ))}
          {!detail && <p className="empty">Loading episodes…</p>}
          {detail && !localChapters.length && !newlyDownloaded.length && (
            <p className="empty">No downloaded episode paths recorded yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Failed chapters modal ────────────────────────────────────── */
function FailedModal({
  jobs,
  loading,
  onClose,
}: {
  jobs: Job[];
  loading: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal modal-sm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>Failed chapters</h2>
            <p>{jobs.length.toLocaleString()} failed download jobs</p>
          </div>
          <button className="btn-ghost btn-sm" onClick={onClose}>
            <X size={14} /> Close
          </button>
        </div>

        <div className="failed-list">
          {loading && <p className="empty">Loading failed chapters…</p>}
          {!loading && jobs.map((job) => (
            <div className="failed-row" key={job.id}>
              <div>
                <strong>{job.manga_title ?? "Unknown book"}</strong>
                <span className="fail-ch">
                  Chapter {job.chapter_key ?? job.chapter_label ?? "unknown"}
                </span>
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

/* ── Mini action button ───────────────────────────────────────── */
function MiniBtn({
  icon,
  label,
  onClick,
  disabled,
}: {
  icon: React.ReactElement;
  label: string;
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <button
      className="btn-ghost btn-sm"
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      disabled={disabled}
    >
      {icon} {label}
    </button>
  );
}
