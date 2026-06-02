import { FormEvent, useEffect, useRef, useState } from "react";
import {
  Download,
  LayoutDashboard,
  Lock,
  LogOut,
  Pause,
  Play,
  RefreshCw,
  Search,
  Settings,
} from "lucide-react";
import {
  api,
  AuthStatus,
  BrowseFilters,
  DebugThreads,
  DownloadProgress,
  Summary,
} from "./api";
import { DashboardPage } from "./pages/DashboardPage";
import { DownloadsPage } from "./pages/DownloadsPage";
import { SearchPage } from "./pages/SearchPage";
import { SettingsPage } from "./pages/SettingsPage";

type Tab = "dashboard" | "downloads" | "search" | "settings";

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

export type SharedProps = {
  summary: Summary;
  progress: DownloadProgress[];
  loading: boolean;
  status: string;
  runAction: (label: string, action: () => Promise<unknown>) => Promise<void>;
  refresh: () => Promise<void>;
};

export function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [summary, setSummary] = useState<Summary>(emptySummary);
  const [progress, setProgress] = useState<DownloadProgress[]>([]);
  const [debugThreads, setDebugThreads] = useState<DebugThreads | null>(null);
  const [browseFilters, setBrowseFilters] = useState<BrowseFilters | null>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [activeTab, setActiveTab] = useState<Tab>("dashboard");

  const browseFiltersRef = useRef(browseFilters);
  browseFiltersRef.current = browseFilters;

  async function refresh() {
    const nextAuth = await api.authStatus();
    setAuthStatus(nextAuth);
    if (!nextAuth.authenticated) return;
    const [nextSummary, nextProgress, nextThreads] = await Promise.all([
      api.summary(),
      api.progress(),
      api.debugThreads(),
    ]);
    setSummary(nextSummary);
    setProgress(nextProgress);
    setDebugThreads(nextThreads);
    if (!browseFiltersRef.current) {
      setBrowseFilters(await api.asuraFilters());
    }
  }

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
        typeof (result as { reason: string }).reason === "string"
      ) {
        setStatus(`${label}: ${(result as { reason: string }).reason}`);
      } else {
        setStatus(`${label} started`);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh().catch((e) => setStatus(e instanceof Error ? e.message : String(e)));
    const h = setInterval(
      () => refresh().catch((e) => setStatus(e instanceof Error ? e.message : String(e))),
      5000,
    );
    return () => clearInterval(h);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!authStatus) {
    return (
      <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", color: "var(--text-2)" }}>
        Loading…
      </div>
    );
  }

  if (!authStatus.authenticated) {
    return (
      <AuthScreen
        authStatus={authStatus}
        onAuthenticated={async () => {
          await refresh();
        }}
      />
    );
  }

  const activeDownloads = progress.reduce((s, p) => s + p.running + p.queued, 0);

  const shared: SharedProps = { summary, progress, loading, status, runAction, refresh };

  const tabs: Array<{ id: Tab; label: string; icon: React.ReactElement; badge?: number }> = [
    { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={15} /> },
    { id: "downloads", label: "Downloads", icon: <Download size={15} />, badge: activeDownloads || undefined },
    { id: "search",    label: "Search",    icon: <Search size={15} /> },
    { id: "settings",  label: "Settings",  icon: <Settings size={15} /> },
  ];

  return (
    <div className="shell">
      {/* ── Sidebar (desktop) ── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img className="sidebar-logo" src="/site-icon2.png" alt="" />
          <div>
            <div className="sidebar-title">MangaCrawler</div>
            <div className="sidebar-sub">{summary.libraryRoot || "No library path"}</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`nav-item${activeTab === tab.id ? " active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="icon">{tab.icon}</span>
              {tab.label}
              {tab.badge != null && (
                <span className="nav-badge">{tab.badge > 999 ? "999+" : tab.badge}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-user">
            <strong>{authStatus.username}</strong>
            <span>{summary.komgaUrl || "Komga not configured"}</span>
          </div>
          <button
            className={`nav-item${summary.queuePaused ? " active" : ""}`}
            onClick={() =>
              runAction(
                summary.queuePaused ? "Queue resume" : "Queue pause",
                summary.queuePaused ? api.resumeQueue : api.pauseQueue,
              )
            }
            disabled={loading}
            title={summary.queuePaused ? "Resume queue" : "Pause queue"}
          >
            <span className="icon">
              {summary.queuePaused ? <Play size={15} /> : <Pause size={15} />}
            </span>
            {summary.queuePaused ? "Resume queue" : "Pause queue"}
          </button>
          <button
            className="nav-item"
            onClick={() =>
              runAction("Logout", async () => {
                await api.logout();
                setAuthStatus(await api.authStatus());
              })
            }
            disabled={loading}
          >
            <span className="icon"><LogOut size={15} /></span>
            Logout
          </button>
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="main">
        {/* Mobile header */}
        <div className="mobile-header">
          <div className="mobile-brand">
            <img src="/site-icon2.png" alt="" style={{ width: 22, height: 22, borderRadius: 4 }} />
            MangaCrawler
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn-ghost btn-sm" onClick={() => refresh()} disabled={loading}>
              <RefreshCw size={13} />
            </button>
            <button
              className={`btn-sm ${summary.queuePaused ? "btn-primary" : "btn-ghost"}`}
              onClick={() =>
                runAction(
                  summary.queuePaused ? "Queue resume" : "Queue pause",
                  summary.queuePaused ? api.resumeQueue : api.pauseQueue,
                )
              }
              disabled={loading}
            >
              {summary.queuePaused ? <Play size={13} /> : <Pause size={13} />}
            </button>
          </div>
        </div>

        {/* Page content */}
        <div className="page">
          {activeTab === "dashboard" && (
            <DashboardPage {...shared} debugThreads={debugThreads} />
          )}
          {activeTab === "downloads" && <DownloadsPage {...shared} />}
          {activeTab === "search" && (
            <SearchPage {...shared} browseFilters={browseFilters} />
          )}
          {activeTab === "settings" && <SettingsPage {...shared} />}
        </div>

        {/* Bottom nav (mobile) */}
        <nav className="bottom-nav">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`btm-nav-item${activeTab === tab.id ? " active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>
      </main>
    </div>
  );
}

/* ── Auth screen ──────────────────────────────────────────────── */
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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <img className="auth-logo" src="/site-icon2.png" alt="" />
        <div className="auth-icon">
          <Lock size={20} />
        </div>
        <h1>{mode === "register" ? "Create account" : "Log in"}</h1>
        <p>
          {mode === "register"
            ? "First startup — create the owner account. Registration closes after this."
            : "Registration is closed. Use the owner account to continue."}
        </p>
        <div className="auth-field">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
        </div>
        <div className="auth-field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "register" ? "new-password" : "current-password"}
          />
        </div>
        {error && <div className="auth-err">{error}</div>}
        <button
          className="btn-primary"
          style={{ height: 40 }}
          disabled={loading || !username.trim() || !password}
        >
          {mode === "register" ? "Register" : "Log in"}
        </button>
      </form>
    </div>
  );
}
