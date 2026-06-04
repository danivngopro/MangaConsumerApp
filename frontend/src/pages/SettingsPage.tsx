import { FormEvent, useEffect, useState } from "react";
import { FolderSync } from "lucide-react";
import { api } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";

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
              <button
                className="btn-ghost btn-sm"
                title="Move each local book into its 0-50 / 50-100 / … / 500+ chapter-range Komga library"
                onClick={() =>
                  runAction("Reorganize by chapter count", api.reorganizeLibrary)
                }
                disabled={loading || summary.queuedJobs + summary.runningJobs > 0}
              >
                <FolderSync size={13} /> Reorganize by chapters
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
