import { FormEvent, useEffect, useState } from "react";
import { FolderSync, GitMerge, Layers, Wrench, Square, Zap, CheckCircle2, XCircle, Loader, Clock, Ban } from "lucide-react";
import { api, FlushTask, FullOrganizeStatus } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";

function TaskIcon({ status }: { status: FlushTask["status"] }) {
  if (status === "running")   return <Loader size={15} style={{ animation: "spin 1s linear infinite" }} />;
  if (status === "done")      return <CheckCircle2 size={15} style={{ color: "var(--accent)" }} />;
  if (status === "error")     return <XCircle size={15} style={{ color: "var(--red, #ef4444)" }} />;
  if (status === "cancelled") return <Ban size={15} style={{ color: "var(--text-3)" }} />;
  return <Clock size={15} style={{ color: "var(--text-3)" }} />;
}

function TaskBar({ status }: { status: FlushTask["status"] }) {
  const color =
    status === "done"      ? "var(--accent)"              :
    status === "error"     ? "var(--red, #ef4444)"        :
    status === "running"   ? "var(--accent)"              :
    status === "cancelled" ? "var(--border)"              :
                             "var(--border)";
  const width =
    status === "done"    ? "100%" :
    status === "error"   ? "100%" :
    status === "pending" ? "0%"   :
    status === "cancelled" ? "0%" :
    "40%"; // running: partial fill
  return (
    <div style={{ height: 3, background: "var(--border)", borderRadius: 2, marginTop: 4, overflow: "hidden" }}>
      <div style={{
        height: "100%", width, background: color, borderRadius: 2,
        transition: "width 0.4s ease",
        animation: status === "running" ? "pulse-bar 1.4s ease-in-out infinite" : undefined,
      }} />
    </div>
  );
}

function FlushCard({ flushRunning, loading }: { flushRunning: boolean; loading: boolean }) {
  const [tasks, setTasks] = useState<FlushTask[]>([]);
  const [everStarted, setEverStarted] = useState(false);

  useEffect(() => {
    if (!flushRunning) return;
    const interval = setInterval(async () => {
      try {
        const status = await api.systemFlushStatus();
        setTasks(status.tasks);
        if (!status.running) clearInterval(interval);
      } catch {
        clearInterval(interval);
      }
    }, 1500);
    return () => clearInterval(interval);
  }, [flushRunning]);

  async function startFlush() {
    setEverStarted(true);
    setTasks([]);
    try {
      await api.systemFlush();
      const status = await api.systemFlushStatus();
      setTasks(status.tasks);
    } catch (e) {
      console.error(e);
    }
  }

  async function stopFlush() {
    await api.systemFlushStop();
  }

  const done    = tasks.filter((t) => t.status === "done").length;
  const total   = tasks.length;
  const hasError = tasks.some((t) => t.status === "error");

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Zap size={16} style={{ color: "var(--accent)" }} />
        System Flush
      </div>

      <p style={{ color: "var(--text-2)", marginBottom: 14, lineHeight: 1.5 }}>
        Full automated reset: pauses downloads, clears the queue, reindexes your local library,
        runs a complete Asura Scans catalog scan, queues every missing chapter, and syncs all
        metadata to Komga. Also sets 5 concurrent downloads · 3 browser pages · 5 image workers
        · auto Komga import &amp; reorganize enabled.
      </p>

      {everStarted && tasks.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
          {/* Overall bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <div style={{ flex: 1, height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: total ? `${(done / total) * 100}%` : "0%",
                background: hasError ? "var(--red, #ef4444)" : "var(--accent)",
                borderRadius: 3,
                transition: "width 0.4s ease",
              }} />
            </div>
            <span style={{ fontSize: 12, color: "var(--text-3)", whiteSpace: "nowrap" }}>{done}/{total}</span>
          </div>

          {tasks.map((task) => (
            <div key={task.id}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <TaskIcon status={task.status} />
                <span style={{ fontWeight: 500, flex: 1 }}>{task.label}</span>
                {task.detail && (
                  <span style={{ fontSize: 12, color: "var(--text-3)" }}>{task.detail}</span>
                )}
              </div>
              <TaskBar status={task.status} />
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {flushRunning ? (
          <button
            className="btn-ghost btn-sm danger"
            onClick={stopFlush}
            disabled={loading}
          >
            <Square size={13} /> Stop flush
          </button>
        ) : (
          <button
            className="btn-primary"
            style={{ height: 40, paddingInline: 20, display: "flex", alignItems: "center", gap: 8 }}
            onClick={startFlush}
            disabled={loading || flushRunning}
          >
            <Zap size={15} /> Run System Flush
          </button>
        )}
        {everStarted && !flushRunning && tasks.length > 0 && (
          <span style={{ fontSize: 12, color: hasError ? "var(--red, #ef4444)" : "var(--accent)" }}>
            {hasError ? "Completed with errors" : "Completed"}
          </span>
        )}
      </div>
    </div>
  );
}

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div style={{ height: 4, background: "var(--border)", borderRadius: 2, overflow: "hidden", marginTop: 6 }}>
      <div style={{
        height: "100%", width: `${pct}%`, background: "var(--accent)", borderRadius: 2,
        transition: "width 0.4s ease",
      }} />
    </div>
  );
}

function ReorgProgress({ running }: { running: boolean }) {
  const [prog, setProg] = useState<{ total: number; processed: number; moved: number; current: string } | null>(null);

  useEffect(() => {
    if (!running) { setProg(null); return; }
    const iv = setInterval(async () => {
      try {
        const s = await api.reorganizeStatus();
        if (s.progress) setProg(s.progress);
        if (!s.running) clearInterval(iv);
      } catch { clearInterval(iv); }
    }, 1200);
    return () => clearInterval(iv);
  }, [running]);

  if (!running || !prog) return null;
  const pct = prog.total ? Math.round((prog.processed / prog.total) * 100) : 0;
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-3)", marginBottom: 2 }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "60%" }}>{prog.current}</span>
        <span style={{ whiteSpace: "nowrap" }}>{prog.processed}/{prog.total} · {prog.moved} moved</span>
      </div>
      <ProgressBar pct={pct} />
    </div>
  );
}

function DedupProgress({ running }: { running: boolean }) {
  const [prog, setProg] = useState<{ phase: string; total: number; processed: number; deleted: number; current: string } | null>(null);

  useEffect(() => {
    if (!running) { setProg(null); return; }
    const iv = setInterval(async () => {
      try {
        const s = await api.deduplicateStatus();
        if (s.progress) setProg(s.progress);
        if (!s.running) clearInterval(iv);
      } catch { clearInterval(iv); }
    }, 1200);
    return () => clearInterval(iv);
  }, [running]);

  if (!running || !prog) return null;
  const pct = prog.total ? Math.round((prog.processed / prog.total) * 100) : 0;
  const label = prog.phase === "comparing"
    ? `Comparing ${prog.processed}/${prog.total}`
    : `${prog.deleted} deleted`;
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-3)", marginBottom: 2 }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "60%" }}>{prog.current}</span>
        <span style={{ whiteSpace: "nowrap" }}>{label}</span>
      </div>
      <ProgressBar pct={pct} />
    </div>
  );
}

function FullOrganizeCard({ running, loading }: { running: boolean; loading: boolean }) {
  const [tasks, setTasks]       = useState<FullOrganizeStatus["tasks"]>([]);
  const [subProg, setSubProg]   = useState<FullOrganizeStatus["subProgress"]>(null);
  const [everStarted, setEverStarted] = useState(false);

  useEffect(() => {
    if (!running) return;
    const iv = setInterval(async () => {
      try {
        const s = await api.fullOrganizeStatus();
        setTasks(s.tasks);
        setSubProg(s.subProgress);
        if (!s.running) clearInterval(iv);
      } catch { clearInterval(iv); }
    }, 1200);
    return () => clearInterval(iv);
  }, [running]);

  async function start() {
    setEverStarted(true);
    setTasks([]);
    setSubProg(null);
    try {
      await api.fullOrganizeStart();
      const s = await api.fullOrganizeStatus();
      setTasks(s.tasks);
      setSubProg(s.subProgress);
    } catch (e) { console.error(e); }
  }

  async function stop() { await api.fullOrganizeStop(); }

  const done     = tasks.filter((t) => t.status === "done").length;
  const hasError = tasks.some((t) => t.status === "error");

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Layers size={16} style={{ color: "var(--accent)" }} />
        Full Library Organize
      </div>

      <p style={{ color: "var(--text-2)", marginBottom: 14, lineHeight: 1.5 }}>
        Runs <strong>Reorganize by chapters</strong> → <strong>Fix Komga libraries</strong> → <strong>Deduplicate books</strong> in sequence.
        Each step shows its own progress.
      </p>

      {everStarted && tasks.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 }}>
          {/* Overall bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ flex: 1, height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: tasks.length ? `${(done / tasks.length) * 100}%` : "0%",
                background: hasError ? "var(--red, #ef4444)" : "var(--accent)",
                borderRadius: 3,
                transition: "width 0.4s ease",
              }} />
            </div>
            <span style={{ fontSize: 12, color: "var(--text-3)", whiteSpace: "nowrap" }}>{done}/{tasks.length}</span>
          </div>

          {tasks.map((task) => {
            const isRunning = task.status === "running";
            const pct = isRunning && subProg?.total
              ? Math.round(((subProg.processed ?? 0) / subProg.total) * 100)
              : undefined;

            return (
              <div key={task.id}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <TaskIcon status={task.status} />
                  <span style={{ fontWeight: 500, flex: 1 }}>{task.label}</span>
                  {task.detail && (
                    <span style={{ fontSize: 12, color: "var(--text-3)", textAlign: "right", maxWidth: "55%" }}>{task.detail}</span>
                  )}
                </div>
                {isRunning && pct !== undefined ? (
                  <ProgressBar pct={pct} />
                ) : (
                  <TaskBar status={task.status} />
                )}
                {isRunning && subProg?.current && (
                  <div style={{
                    fontSize: 11, color: "var(--text-3)", marginTop: 3,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>
                    {subProg.current}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {running ? (
          <button className="btn-ghost btn-sm danger" onClick={stop} disabled={loading}>
            <Square size={13} /> Stop
          </button>
        ) : (
          <button
            className="btn-primary"
            style={{ height: 40, paddingInline: 20, display: "flex", alignItems: "center", gap: 8 }}
            onClick={start}
            disabled={loading}
          >
            <Layers size={15} /> Full Library Organize
          </button>
        )}
        {everStarted && !running && tasks.length > 0 && (
          <span style={{ fontSize: 12, color: hasError ? "var(--red, #ef4444)" : "var(--accent)" }}>
            {hasError ? "Completed with errors" : "Completed"}
          </span>
        )}
      </div>
    </div>
  );
}

export function SettingsPage({ summary, loading, runAction }: SharedProps) {
  const [intervalDays,          setIntervalDays]          = useState(summary.autoScanEveryDays);
  const [downloadConcurrency,   setDownloadConcurrency]   = useState(summary.downloadConcurrency);
  const [browserConcurrency,    setBrowserConcurrency]    = useState(summary.browserConcurrency);
  const [imageDownloadWorkers,  setImageDownloadWorkers]  = useState(summary.imageDownloadWorkers);
  const [readerEngine,          setReaderEngine]          = useState<"playwright" | "selenium">(summary.readerEngine);
  const [komgaAutoEnabled,      setKomgaAutoEnabled]      = useState(summary.komgaAutoEnabled);
  const [reorganizeOnDrain,     setReorganizeOnDrain]     = useState(summary.reorganizeOnDrain);

  // Sync from backend on every summary refresh
  useEffect(() => {
    setIntervalDays(summary.autoScanEveryDays);
    setDownloadConcurrency(summary.downloadConcurrency);
    setBrowserConcurrency(summary.browserConcurrency);
    setImageDownloadWorkers(summary.imageDownloadWorkers);
    setReaderEngine(summary.readerEngine);
    setKomgaAutoEnabled(summary.komgaAutoEnabled);
    setReorganizeOnDrain(summary.reorganizeOnDrain);
  }, [
    summary.autoScanEveryDays,
    summary.downloadConcurrency,
    summary.browserConcurrency,
    summary.imageDownloadWorkers,
    summary.readerEngine,
    summary.komgaAutoEnabled,
    summary.reorganizeOnDrain,
  ]);

  async function submitSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction("Save settings", () =>
      api.updateSettings(
        intervalDays,
        downloadConcurrency,
        browserConcurrency,
        imageDownloadWorkers,
        readerEngine,
        komgaAutoEnabled,
        reorganizeOnDrain,
      ),
    );
  }

  return (
    <>
      <div className="page-header">
        <div className="page-title-row">
          <h2>Settings</h2>
        </div>
      </div>

      <div className="settings-grid">
        {/* Settings form */}
        <div className="card">
          <div className="card-title">Configuration</div>
          <form className="settings-fields" onSubmit={submitSettings}>
            <div className="field-row">
              <label htmlFor="interval">Auto scan every</label>
              <input
                id="interval"
                type="number"
                min={0}
                value={intervalDays}
                onChange={(e) => setIntervalDays(Number(e.target.value))}
              />
              <span style={{ color: "var(--text-3)", fontSize: 13 }}>days</span>
              <span className="field-help" style={{ flexBasis: "100%" }}>
                0 disables auto-scheduling. Enabled scans run at 2:00 AM.
              </span>
            </div>

            <div className="field-row">
              <label htmlFor="dlc">Concurrent downloads</label>
              <input
                id="dlc"
                type="number"
                min={1}
                max={6}
                value={downloadConcurrency}
                onChange={(e) => setDownloadConcurrency(Number(e.target.value))}
              />
            </div>

            <div className="field-row">
              <label htmlFor="brc" title="Limit simultaneous rendered reader pages. Lower values reduce CPU.">
                Browser pages
              </label>
              <input
                id="brc"
                type="number"
                min={1}
                max={4}
                value={browserConcurrency}
                onChange={(e) => setBrowserConcurrency(Number(e.target.value))}
              />
              <span className="field-help" style={{ flexBasis: "100%" }}>
                Controls CPU-heavy reader rendering
              </span>
            </div>

            <div className="field-row">
              <label htmlFor="img" title="Limit parallel HTTP image downloads per chapter.">
                Image workers
              </label>
              <input
                id="img"
                type="number"
                min={1}
                max={8}
                value={imageDownloadWorkers}
                onChange={(e) => setImageDownloadWorkers(Number(e.target.value))}
              />
              <span className="field-help" style={{ flexBasis: "100%" }}>
                Controls HTTP transfer parallelism
              </span>
            </div>

            <div className="field-row">
              <label htmlFor="eng" title="Playwright uses one shared browser process. Selenium is available as fallback.">
                Reader engine
              </label>
              <select
                id="eng"
                value={readerEngine}
                onChange={(e) => setReaderEngine(e.target.value as "playwright" | "selenium")}
                style={{ width: "auto" }}
              >
                <option value="playwright">Playwright</option>
                <option value="selenium">Selenium</option>
              </select>
            </div>

            <div className="field-row">
              <input
                id="komga-auto"
                type="checkbox"
                checked={komgaAutoEnabled}
                onChange={(e) => setKomgaAutoEnabled(e.target.checked)}
              />
              <label htmlFor="komga-auto">Auto Komga import/scan after downloads</label>
              <span className="field-help" style={{ flexBasis: "100%" }}>
                Imports after the whole queue finishes, then waits 1 hour before a fast scan of all Komga libraries.
              </span>
            </div>

            <div className="field-row">
              <input
                id="reorg-drain"
                type="checkbox"
                checked={reorganizeOnDrain}
                onChange={(e) => setReorganizeOnDrain(e.target.checked)}
              />
              <label htmlFor="reorg-drain">Auto reorganize by chapter count after downloads</label>
              <span className="field-help" style={{ flexBasis: "100%" }}>
                Moves each book into the correct 0–50 / 50–100 / … / 500+ library after the queue drains. Requires "Auto Komga import/scan" to be enabled.
              </span>
            </div>

            <button
              className="btn-primary"
              style={{ width: "fit-content", height: 38 }}
              disabled={loading}
            >
              Save settings
            </button>
          </form>
        </div>

        {/* System info */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card">
            <div className="card-title">System Info</div>
            <div className="sys-grid">
              <StatCard label="Library root" value={summary.libraryRoot || "Not configured"} />
              <StatCard label="Komga URL"    value={summary.komgaUrl || "Not configured"} />
              <StatCard
                label="Last scan"
                value={summary.lastScanAt ? new Date(summary.lastScanAt).toLocaleString() : "Never"}
              />
              <StatCard
                label="Scan status"
                value={
                  summary.scanRunning
                    ? "Running"
                    : summary.limitedScanActive
                    ? "Top-up active"
                    : "Idle"
                }
              />
            </div>
          </div>

          <div className="card">
            <div className="card-title">Queue</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <StatCard label="Queued + Running" value={`${summary.queuedJobs + summary.runningJobs}`} />
              <StatCard label="Paused"           value={`${summary.pausedJobs}`} />
              <StatCard label="Failed"           value={`${summary.failedJobs}`} />
            </div>
            <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                className="btn-ghost btn-sm"
                onClick={() =>
                  runAction("Retry failed downloads", api.retryFailedDownloads)
                }
                disabled={loading || summary.failedJobs === 0}
              >
                Retry failed
              </button>
              {summary.reorganizeRunning ? (
                <button
                  className="btn-ghost btn-sm danger"
                  onClick={() => runAction("Stop reorganize", api.reorganizeStop)}
                  disabled={loading}
                >
                  <Square size={13} /> Stop reorganize
                </button>
              ) : (
                <button
                  className="btn-ghost btn-sm"
                  title="Move each local book into its 0-50 / 50-100 / … / 500+ chapter-range Komga library"
                  onClick={() => runAction("Reorganize by chapter count", api.reorganizeLibrary)}
                  disabled={loading}
                >
                  <FolderSync size={13} /> Reorganize by chapters
                </button>
              )}
              <button
                className="btn-ghost btn-sm"
                title="Delete all per-book Komga libraries and rescan range libraries — fixes a broken previous run"
                onClick={() => runAction("Fix Komga libraries", api.komgaCleanup)}
                disabled={loading || summary.reorganizeRunning}
              >
                <Wrench size={13} /> Fix Komga libraries
              </button>
              {summary.deduplicateRunning ? (
                <button
                  className="btn-ghost btn-sm danger"
                  onClick={() => runAction("Stop deduplication", api.deduplicateStop)}
                  disabled={loading}
                >
                  <Square size={13} /> Stop dedup
                </button>
              ) : (
                <button
                  className="btn-ghost btn-sm"
                  title="Find duplicate books (same/similar title) across all range folders and keep the one with the most chapters"
                  onClick={() => runAction("Deduplicate library", api.deduplicateLibrary)}
                  disabled={loading || summary.reorganizeRunning}
                >
                  <GitMerge size={13} /> Deduplicate books
                </button>
              )}
            </div>
            <ReorgProgress running={summary.reorganizeRunning} />
            <DedupProgress running={summary.deduplicateRunning} />
          </div>
        </div>
      </div>

      {/* ── Full Library Organize ── */}
      <FullOrganizeCard running={summary.fullOrganizeRunning} loading={loading} />

      {/* ── System Flush ── */}
      <FlushCard flushRunning={summary.flushRunning} loading={loading} />
    </>
  );
}
