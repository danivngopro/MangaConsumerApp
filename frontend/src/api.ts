export type Summary = {
  knownManga: number;
  localBooks: number;
  localChapters: number;
  queuedJobs: number;
  runningJobs: number;
  failedJobs: number;
  pausedJobs: number;
  missingChapters: number;
  lastScanAt: string | null;
  queuePaused: boolean;
  libraryRoot: string;
  komgaUrl: string;
  autoScanEveryDays: number;
  downloadConcurrency: number;
};

export type Book = {
  id: number;
  title: string;
  url: string;
  cover_url: string | null;
  status: string | null;
  remote_chapter_count: number;
  local_chapter_count: number;
  missing_count: number;
  local_folder: string | null;
  last_scanned_at: string | null;
};

export type BookDetail = Book & {
  downloaded_count: number;
  paused_downloads: boolean;
  komga_library_id: string | null;
  komga_imported_at: string | null;
  komga_scanned_at: string | null;
  komga_last_error: string | null;
  chapters: Array<{
    id: number;
    chapter_key: string;
    label: string;
    is_downloaded: number;
    file_path: string | null;
  }>;
  jobs: Job[];
};

export type Job = {
  id: number;
  type: string;
  status: string;
  attempts: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  manga_title: string | null;
  chapter_label: string | null;
};

export type DownloadProgress = {
  manga_id: number;
  manga_title: string;
  total: number;
  done: number;
  running: number;
  queued: number;
  failed: number;
  percent: number;
};

export type AuthStatus = {
  authenticated: boolean;
  username: string | null;
  registrationOpen: boolean;
};

const API_BASE =
  import.meta.env.VITE_API_BASE ??
  (window.location.port === "5173" ? "http://localhost:8816" : "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  register: (username: string, password: string) =>
    request<AuthStatus>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  login: (username: string, password: string) =>
    request<AuthStatus>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<AuthStatus>("/api/auth/logout", { method: "POST" }),
  summary: () => request<Summary>("/api/summary"),
  books: () => request<Book[]>("/api/books"),
  bookDetail: (mangaId: number) => request<BookDetail>(`/api/books/${mangaId}`),
  jobs: () => request<Job[]>("/api/jobs"),
  progress: () => request<DownloadProgress[]>("/api/progress"),
  fullScan: (limit?: number | null) =>
    request<{ started: boolean; limit: number | null }>("/api/scan/full", {
      method: "POST",
      body: JSON.stringify({ limit: limit || null }),
    }),
  libraryScan: () =>
    request<{ books: number; chapters: number; error: string | null }>(
      "/api/scan/library",
      { method: "POST" },
    ),
  specificScan: (query: string) =>
    request<{ started: boolean; query: string }>("/api/scan/specific", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  updateSettings: (autoScanEveryDays: number, downloadConcurrency: number) =>
    request<Summary>("/api/settings", {
      method: "POST",
      body: JSON.stringify({ autoScanEveryDays, downloadConcurrency }),
    }),
  pauseQueue: () =>
    request<{ queuePaused: boolean }>("/api/queue/pause", { method: "POST" }),
  resumeQueue: () =>
    request<{ queuePaused: boolean }>("/api/queue/resume", { method: "POST" }),
  pauseBookDownloads: (mangaId: number) =>
    request<{ paused: number; mangaId: number }>(`/api/books/${mangaId}/downloads/pause`, {
      method: "POST",
    }),
  resumeBookDownloads: (mangaId: number) =>
    request<{ resumed: number; mangaId: number }>(`/api/books/${mangaId}/downloads/resume`, {
      method: "POST",
    }),
  retryFailedDownloads: () =>
    request<{ requeued: number }>("/api/jobs/retry-failed", { method: "POST" }),
  retryFailedBookDownloads: (mangaId: number) =>
    request<{ requeued: number; mangaId: number }>(`/api/books/${mangaId}/downloads/retry-failed`, {
      method: "POST",
    }),
  quickScanBook: (mangaId: number) =>
    request<{
      scanned: boolean;
      libraryId: string;
      title: string;
      deep: boolean;
    }>(`/api/komga/books/${mangaId}/quick-scan`, { method: "POST" }),
  quickScanAll: () =>
    request<{ scanned: boolean; libraryCount: number; deep: boolean }>(
      "/api/komga/quick-scan-all",
      {
        method: "POST",
      },
    ),
};
