import { FormEvent, useEffect, useRef, useState } from "react";
import {
  Activity,
  BookOpen,
  ChevronDown,
  Clock,
  Download,
  Pause,
  RefreshCw,
  Search,
  Server,
  X,
  Zap,
} from "lucide-react";
import { api, DebugThreads, LogEntry } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";

type Props = SharedProps & { debugThreads: DebugThreads | null };

export function DashboardPage({ summary, progress, debugThreads, loading, status, runAction, refresh }: Props) {
  const [scanLimit, setScanLimit] = useState(summary.limitedScanActiveThreshold || 300);
  const [scanLimitFocused, setScanLimitFocused] = useState(false);
  const [query, setQuery] = useState("");
  const [threadsOpen, setThreadsOpen] = useState(false);
  const [logThread, setLogThread] = useState<{ name: string; job: Record<string, unknown> | null } | null>(null);

  const focusedRef = useRef(scanLimitFocused);
  focusedRef.current = scanLimitFocused;

  useEffect(() => {
    if (!focusedRef.current) {
      setScanLimit(summary.limitedScanActiveThreshold);
    }
  }, [summary.limitedScanActiveThreshold]);

  function updateScanLimit(value: number) {
    setScanLimit(value);
    if (!Number.isFinite(value) || value < 1 || value > 5000) return;
    api.updateTopUpThreshold(value).catch(() => {});
  }

  async function submitSpecific(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    await runAction("Specific scan", () => api.specificScan(query.trim()));
    setQuery("");
  }

  async function confirmKomgaScanAll() {
    if (!window.confirm("Run a quick Komga scan for every library? This is not a deep scan, but can be heavy.")) return;
    await runAction("Komga quick scan all", api.quickScanAll);
  }

  async function confirmEnqueueMissing() {
    if (!window.confirm(`Enqueue all ${summary.missingChapters.toLocaleString()} missing chapters for download? This creates jobs for every catalog chapter not yet downloaded, without re-scraping Asura.`)) return;
    await runAction("Re-enqueue missing", api.enqueueMissing);
  }

  // Overall progress totals
  const totalDone   = progress.reduce((s, p) => s + p.done, 0);
  const totalQueue  = progress.reduce((s, p) => s + p.queued + p.running, 0);
  const totalPaused = progress.reduce((s, p) => s + p.paused, 0);
  const totalFailed = progress.reduce((s, p) => s + p.failed, 0);
  const totalActive = totalQueue + totalPaused + totalFailed;
  const totalItems  = totalDone + totalActive;
  const overallPct  = totalItems > 0 ? Math.round((totalDone / totalItems) * 100) : 0;

  const activeLabel = [
    totalQueue  > 0 && `${totalQueue} in queue`,
    totalPaused > 0 && `${totalPaused} paused`,
    totalFailed > 0 && `${totalFailed} failed`,
  ].filter(Boolean).join(", ");

  return (
    <>
      {/* Page header */}
      <div className="page-header">
        <div className="page-title-row">
          <h2>Dashboard</h2>
          {summary.scanRunning && <span className="tag tag-purple">Scanning…</span>}
          {summary.limitedScanActive && <span className="tag tag-yellow">Top-up active</span>}
          {summary.failedJobs > 0 && (
            <span className="tag tag-red">{summary.failedJobs} failed</span>
          )}
        </div>
        <div className="page-actions">
          <button className="btn-ghost btn-sm" onClick={refresh} disabled={loading}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* Metrics */}
      <div className="metrics-grid">
        <Metric icon={<BookOpen size={14} />} label="Local Books"      value={summary.localBooks} />
        <Metric icon={<Download size={14} />} label="Chapters"         value={summary.localChapters} />
        <Metric icon={<Search size={14} />}   label="Known Titles"     value={summary.knownManga} />
        <Metric icon={<Clock size={14} />}    label="Missing"          value={summary.missingChapters} />
        <Metric icon={<Activity size={14} />} label="Queued + Running" value={summary.queuedJobs + summary.runningJobs} />
        <Metric icon={<Pause size={14} />}    label="Paused"           value={summary.pausedJobs} />
        <Metric
          icon={<Server size={14} />}
          label="Failed"
          value={summary.failedJobs}
          tone={summary.failedJobs > 0 ? "warn" : "normal"}
        />
        <Metric
          icon={<Activity size={14} />}
          label="CPU"
          value={Math.round(summary.cpuPercent)}
          suffix="%"
          tone={summary.cpuPercent >= 85 ? "warn" : summary.cpuPercent >= 60 ? "caution" : "normal"}
        />
      </div>

      {/* Total progress bar */}
      {totalItems > 0 && (
        <div className="card total-bar" style={{ marginBottom: 14 }}>
          <div className="total-bar-header">
            <span className="total-bar-label">
              <Download size={13} /> Overall Progress
            </span>
            <span>{totalDone.toLocaleString()} / {totalItems.toLocaleString()} episodes</span>
            <span className="total-bar-pct">{overallPct}%</span>
            {totalActive > 0 && <span className="total-bar-extra">{activeLabel}</span>}
          </div>
          <div className="track">
            <div className="track-fill" style={{ width: `${Math.min(100, overallPct)}%` }} />
          </div>
        </div>
      )}

      {/* Scan controls */}
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-title"><RefreshCw size={12} /> Scan Controls</div>

        <div className="scan-actions">
          <button
            className="btn-primary"
            onClick={() => runAction("Full scan", () => api.fullScan(null))}
            disabled={loading}
            title="Scan full Asura catalog and enqueue missing chapters."
          >
            Full scan
          </button>
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
            title="Enqueue all chapters already in the catalog that haven't been downloaded yet, without re-scraping Asura."
          >
            Re-enqueue missing ({summary.missingChapters.toLocaleString()})
          </button>
          <button
            className="btn-ghost"
            onClick={confirmKomgaScanAll}
            disabled={loading}
            title="Quick-scan every Komga library (deep=false)."
          >
            Komga scan all
          </button>
          <button
            className="btn-ghost"
            onClick={() => runAction("Import all libraries", api.importAllBooks)}
            disabled={loading}
            title="Create Komga libraries for uncreated folders, then shallow-scan. Runs in background."
          >
            Import all
          </button>
        </div>

        <div className="topup-row">
          <label>
            Top-up if active chapters below
            <input
              type="number"
              min={1}
              max={5000}
              value={scanLimit}
              onFocus={() => setScanLimitFocused(true)}
              onBlur={() => setScanLimitFocused(false)}
              onChange={(e) => updateScanLimit(Number(e.target.value))}
            />
            chapters
          </label>
          <button
            className="btn-ghost"
            onClick={() =>
              runAction(`Top-up below ${scanLimit} active chapters`, () =>
                api.startTopUp(scanLimit),
              )
            }
            disabled={loading}
          >
            <Zap size={13} /> Start top-up
          </button>
        </div>

        <form className="specific-row" onSubmit={submitSpecific}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Manga title or Asura URL"
          />
          <button className="btn-ghost" disabled={loading || !query.trim()}>
            Scan manga
          </button>
        </form>

        <div className="status-bar" style={{ marginTop: 2 }}>
          <span className="status-dot" />
          {status}
        </div>

        <div className="muted" style={{ marginTop: 8 }}>
          Komga: {summary.komgaUrl || "not configured"} ·{" "}
          Last scan: {summary.lastScanAt ? new Date(summary.lastScanAt).toLocaleString() : "never"}
        </div>
      </div>

      {/* Thread panel */}
      {debugThreads && (
        <div className="card">
          <button
            type="button"
            style={{
              width: "100%", height: "auto", background: "transparent", border: 0,
              borderRadius: 6, padding: "2px 0", display: "flex", alignItems: "center",
              gap: 7, fontSize: 11, fontWeight: 600, color: "var(--text-3)",
              textTransform: "uppercase", letterSpacing: "0.06em", cursor: "pointer",
              marginBottom: threadsOpen ? 14 : 0,
            }}
            onClick={() => setThreadsOpen((v) => !v)}
          >
            <Activity size={12} /> Active Threads
            <ChevronDown
              size={13}
              style={{
                marginLeft: "auto",
                transition: "transform 200ms",
                transform: threadsOpen ? "rotate(180deg)" : "rotate(0deg)",
                color: "var(--purple-hi)",
              }}
            />
          </button>

          {threadsOpen && (
            <ThreadPanel
              debugThreads={debugThreads}
              loading={loading}
              onStopThread={(ident) =>
                runAction(`Stop thread ${ident}`, () => api.stopThread(ident))
              }
              onOpenLogs={(name, job) => setLogThread({ name, job })}
            />
          )}
        </div>
      )}

      {logThread && (
        <ThreadLogModal
          threadName={logThread.name}
          job={logThread.job}
          onClose={() => setLogThread(null)}
        />
      )}
    </>
  );
}

/* ── Metric card ──────────────────────────────────────────────── */
function Metric({
  icon,
  label,
  value,
  suffix,
  tone = "normal",
}: {
  icon: React.ReactElement;
  label: string;
  value: number;
  suffix?: string;
  tone?: "normal" | "caution" | "warn";
}) {
  return (
    <div className={`metric ${tone}`}>
      <div className="metric-icon">{icon}</div>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">
        {value.toLocaleString()}
        {suffix}
      </strong>
    </div>
  );
}

/* ── Thread panel ─────────────────────────────────────────────── */
function ThreadPanel({
  debugThreads,
  loading,
  onStopThread,
  onOpenLogs,
}: {
  debugThreads: DebugThreads;
  loading: boolean;
  onStopThread: (ident: number) => void;
  onOpenLogs: (name: string, job: Record<string, unknown> | null) => void;
}) {
  const activeWorkers = debugThreads.downloadQueue.workers.filter((w) => w.alive);
  const scanThreads = debugThreads.threads.filter(
    (t) => t.name !== "scan-scheduler" && /scan|import/i.test(t.name),
  );

  return (
    <>
      <div className="thread-grid">
        <StatCard label="Scan stop requested" value={debugThreads.scanStopRequested ? "Yes" : "No"} />
        <StatCard label="Scan job"            value={debugThreads.scheduler.scanRunning ? "Running" : "Idle"} />
        <StatCard label="Scheduler"           value={debugThreads.scheduler.thread.alive ? "Alive" : "Stopped"} />
        <StatCard label="Top-up"              value={debugThreads.settings.limitedScanActive ? "Active" : "Off"} />
        <StatCard label="Auto scan days"      value={String(debugThreads.settings.autoScanEveryDays)} />
      </div>

      {debugThreads.scheduler.currentScan && (
        <div className="thread-row" style={{ marginBottom: 6 }}>
          <strong style={{ fontSize: 13 }}>Current scan</strong>
          <span style={{ color: "var(--text-2)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis" }}>
            {JSON.stringify(debugThreads.scheduler.currentScan)}
          </span>
        </div>
      )}

      <div className="thread-list">
        {activeWorkers.map((w) => (
          <div
            className="thread-row thread-row-clickable"
            key={`${w.name}-${w.ident}`}
            onClick={() => onOpenLogs(w.name, w.job ?? null)}
            title="Click to view logs for this worker"
          >
            <div className="thread-info">
              <strong>{w.name}</strong>
              <span>{w.job ? `${w.job.manga ?? ""} — ${w.job.chapter ?? w.job.status ?? ""}` : "Idle worker"}</span>
            </div>
            <button
              className="btn-ghost btn-sm danger"
              disabled={loading || w.ident === null}
              onClick={(e) => { e.stopPropagation(); w.ident !== null && onStopThread(w.ident); }}
              title="Ask this worker to exit after its current chapter."
            >
              Stop
            </button>
          </div>
        ))}
        {scanThreads.map((t) => {
          const stoppable = t.ident !== null && /scan|scheduler/i.test(t.name);
          return (
            <div
              className="thread-row thread-row-clickable"
              key={`${t.name}-${t.ident}`}
              onClick={() => onOpenLogs(t.name, null)}
              title="Click to view logs for this thread"
            >
              <div className="thread-info">
                <strong>{t.name}</strong>
                <span>{t.alive ? "Alive" : "Stopped"}</span>
              </div>
              {stoppable && (
                <button
                  className="btn-ghost btn-sm danger"
                  disabled={loading}
                  onClick={(e) => { e.stopPropagation(); onStopThread(t.ident as number); }}
                  title="Request cancellation for this scan thread."
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
    </>
  );
}

/* ── Thread log modal ─────────────────────────────────────────── */
function ThreadLogModal({
  threadName,
  job,
  onClose,
}: {
  threadName: string;
  job: Record<string, unknown> | null;
  onClose: () => void;
}) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);

  function fetchLogs() {
    api.logs(200).then((data) => {
      setLogs(data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }

  useEffect(() => {
    fetchLogs();
    const id = setInterval(fetchLogs, 1500);
    return () => clearInterval(id);
  }, []);

  // Scroll to bottom on new entries only if already at bottom
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (isAtBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [logs]);

  // Filter logs to ones mentioning this thread when we have thread context
  const filtered = threadName
    ? logs.filter((l) => l.message.includes(`[${threadName}]`) || (job && typeof job.manga === "string" && l.message.includes(job.manga as string)))
    : logs;

  const displayLogs = filtered.length > 0 ? filtered : logs;

  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal modal-sm" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 style={{ fontFamily: "'Fira Code', monospace", fontSize: 15 }}>{threadName}</h2>
            {job && (
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-2)" }}>
                {job.manga ? `${job.manga} — ${job.chapter ?? ""}` : JSON.stringify(job)}
              </p>
            )}
            {!job && <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-3)" }}>Scan thread — showing recent activity</p>}
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <button className="btn-ghost btn-sm" onClick={fetchLogs}>
              <RefreshCw size={12} /> Refresh
            </button>
            <button className="btn-ghost btn-sm" onClick={onClose}><X size={13} /></button>
          </div>
        </div>

        {loading ? (
          <p className="muted" style={{ textAlign: "center", padding: 24 }}>Loading…</p>
        ) : (
          <div
            ref={scrollRef}
            className="log-list"
            onScroll={(e) => {
              const el = e.currentTarget;
              isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
            }}
          >
            {displayLogs.length === 0 ? (
              <p className="empty">No log entries found.</p>
            ) : (
              [...displayLogs].reverse().map((entry) => (
                <div key={entry.id} className={`log-row log-${entry.level}`}>
                  <span className="log-time">{new Date(entry.created_at).toLocaleTimeString()}</span>
                  <span className="log-level">{entry.level}</span>
                  <span className="log-msg">{entry.message}</span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
