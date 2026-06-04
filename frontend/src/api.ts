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
  limitedScanActive: boolean;
  scanRunning: boolean;
  komgaAutoEnabled: boolean;
  reorganizeOnDrain: boolean;
  reorganizeRunning: boolean;
  flushRunning: boolean;
  limitedScanActiveThreshold: number;
  libraryRoot: string;
  komgaUrl: string;
  komgaPublicUrl: string;
  autoScanEveryDays: number;
  downloadConcurrency: number;
  browserConcurrency: number;
  imageDownloadWorkers: number;
  readerEngine: "playwright" | "selenium";
  cpuPercent: number;
  diskTotal: number;
  diskFree: number;
  diskUsed: number;
};

export type Book = {
  id: number;
  title: string;
  url: string;
  cover_url: string | null;
  status: string | null;
  asura_type?: string | null;
  asura_author?: string | null;
  asura_artist?: string | null;
  asura_genres?: Array<{ name?: string; slug?: string } | string>;
  asura_rating?: number | null;
  asura_description?: string | null;
  asura_last_chapter_at?: string | null;
  komga_series_id?: string | null;
  komga_series_url?: string | null;
  metadata_synced_at?: string | null;
  metadata_last_error?: string | null;
  remote_chapter_count: number;
  local_chapter_count: number;
  missing_count: number;
  local_folder: string | null;
  last_scanned_at: string | null;
};

export type BookDetail = Book & {
  downloaded_count: number;
  existing_downloaded_count: number;
  newly_downloaded_count: number;
  paused_downloads: boolean;
  komga_library_id: string | null;
  komga_imported_at: string | null;
  komga_scanned_at: string | null;
  komga_last_error: string | null;
  chapters: Array<{
    id: number;
    chapter_key: string;
    label: string;
    url: string;
    komga_url?: string | null;
    is_downloaded: number;
    file_path: string | null;
  }>;
  latest_read: {
    book_id: string;
    chapter_key: string;
    label: string;
    page: number;
    completed: boolean;
    komga_url: string;
  } | null;
  local_chapters: string[];
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
  chapter_key: string | null;
  chapter_label: string | null;
};

export type DownloadProgress = {
  manga_id: number;
  manga_title: string;
  url: string;
  local_folder: string | null;
  total: number;
  done: number;
  available_count: number;
  existing_downloaded_count: number;
  newly_downloaded_count: number;
  remote_chapter_count: number;
  missing_count: number;
  job_total: number;
  job_done: number;
  running: number;
  queued: number;
  paused: number;
  failed: number;
  percent: number;
};

export type BrowseFilters = {
  genres: Array<{ id: number; name: string; slug: string }>;
  authors: string[];
  artists: string[];
  statuses: string[];
  types: string[];
  sorts: string[];
};

export type BrowseSearchPayload = {
  search: string;
  genres: string[];
  author: string;
  artist: string;
  status: string;
  type: string;
  sort: string;
  order: string;
  minChapters: number;
  maxChapters: number;
  limit: number;
  offset: number;
};

export type BrowseResult = {
  id: number;
  slug: string;
  title: string;
  url: string;
  cover_url: string | null;
  status: string | null;
  type: string | null;
  author: string | null;
  artist: string | null;
  genres: Array<{ id: number; name: string; slug: string }>;
  chapter_count: number;
  rating: number | null;
  last_chapter_at: string | null;
  popularity_rank: number | null;
  is_existing: boolean;
  is_tracked: boolean;
  local_chapter_count: number;
  missing_count: number;
  local_folder: string | null;
};

export type BrowseSearchResponse = {
  items: BrowseResult[];
  total: number;
  limit: number;
  offset: number;
};

export type LocalBrowsePayload = {
  search: string;
  genres: string[];
  status: string;
  type: string;
  sort: string;
  order: string;
  minChapters: number;
  maxChapters: number;
  limit: number;
  offset: number;
};

export type LocalBrowseResponse = {
  items: Book[];
  total: number;
  limit: number;
  offset: number;
};

export type AuthStatus = {
  authenticated: boolean;
  username: string | null;
  registrationOpen: boolean;
};

export type LogEntry = {
  id: number;
  level: string;
  message: string;
  created_at: string;
};

export type DuplicateCandidate = {
  id: number;
  candidate_kind: "remote_local" | "local_local";
  remote_manga_id: number | null;
  remote_title: string;
  remote_folder: string | null;
  local_title: string;
  local_folder: string;
  local_chapter_count: number;
  remote_chapter_count: number;
  score: number;
  reason: string;
  status: "pending" | "confirmed_exists" | "confirmed_new" | "ignored";
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
  download_folder_override: string | null;
  download_title_override: string | null;
};

export type FlushTaskStatus = "pending" | "running" | "done" | "error" | "cancelled";

export type FlushTask = {
  id: string;
  label: string;
  status: FlushTaskStatus;
  detail: string;
};

export type MetadataCandidate = Book & {
  asura_type: string | null;
  asura_author: string | null;
  asura_artist: string | null;
  asura_genres: Array<{ name?: string; slug?: string } | string>;
  asura_rating: number | null;
  asura_description: string | null;
  asura_last_chapter_at: string | null;
  komga_series_id: string | null;
  metadata_synced_at: string | null;
  metadata_last_error: string | null;
};

export type UnmatchedLocalBook = {
  normalized_title: string;
  title: string;
  folder_path: string;
  chapter_count: number;
  chapters: string[];
  updated_at: string;
};

export type MetadataDiscoverResult = {
  processed: number;
  autoLinked: number;
  reviewNeeded: number;
  skipped: number;
  errors: string[];
};

export type DebugThreads = {
  threads: Array<{
    name: string;
    ident: number | null;
    daemon: boolean;
    alive: boolean;
  }>;
  scanStopRequested: boolean;
  scheduler: {
    scanRunning: boolean;
    cancelRequested: boolean;
    currentScan: Record<string, unknown> | null;
    thread: {
      name: string | null;
      ident: number | null;
      alive: boolean;
    };
  };
  downloadQueue: {
    paused: boolean;
    concurrency: number;
    workers: Array<{
      name: string;
      ident: number | null;
      alive: boolean;
      job: Record<string, unknown> | null;
    }>;
  };
  settings: {
    limitedScanActive: boolean;
    limitedScanBatchRunning: boolean;
    limitedScanActiveThreshold: number;
    autoScanEveryDays: number;
    komgaAutoEnabled: boolean;
    browserConcurrency: number;
    imageDownloadWorkers: number;
    readerEngine: "playwright" | "selenium";
  };
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
  failedJobs: () => request<Job[]>("/api/jobs/failed"),
  duplicates: () => request<DuplicateCandidate[]>("/api/duplicates"),
  resolveDuplicate: (candidateId: number, status: "confirmed_exists" | "confirmed_new" | "ignored") =>
    request<{ candidateId: number; status: string; enqueued: number }>(
      `/api/duplicates/${candidateId}/resolve`,
      {
        method: "POST",
        body: JSON.stringify({ status }),
      },
    ),
  deleteDuplicateLocal: (candidateId: number) =>
    request<{ deleted: boolean; folder: string; komgaDeleted: boolean }>(
      `/api/duplicates/${candidateId}/local`,
      { method: "DELETE" },
    ),
  resolveLocalMain: (candidateId: number, mainFolder: string) =>
    request<{ deleted: string | null; transferred: number; mainFolder: string }>(
      `/api/duplicates/${candidateId}/resolve-local-main`,
      { method: "POST", body: JSON.stringify({ main_folder: mainFolder }) },
    ),
  resolveGroupMain: (remoteMangaId: number, mainFolder: string) =>
    request<{ confirmed: number; deleted: number; transferred: number; enqueued: number }>(
      "/api/duplicates/group/resolve-main",
      { method: "POST", body: JSON.stringify({ remote_manga_id: remoteMangaId, main_folder: mainFolder }) },
    ),
  metadataCandidates: () => request<MetadataCandidate[]>("/api/metadata/candidates"),
  metadataUnmatched: () => request<UnmatchedLocalBook[]>("/api/metadata/unmatched"),
  discoverMetadata: (limit?: number | null) =>
    request<MetadataDiscoverResult>("/api/metadata/discover", {
      method: "POST",
      body: JSON.stringify({ limit: limit ?? null }),
    }),
  syncMetadata: (mangaIds?: number[]) =>
    request<{ synced: number; needsReview: number; errors: string[] }>(
      "/api/metadata/sync",
      {
        method: "POST",
        body: JSON.stringify({ mangaIds: mangaIds ?? null }),
      },
    ),
  progress: () => request<DownloadProgress[]>("/api/progress"),
  asuraFilters: () => request<BrowseFilters>("/api/asura/filters"),
  asuraSearch: (payload: BrowseSearchPayload) =>
    request<BrowseSearchResponse>("/api/asura/search", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  browseBooks: (payload: LocalBrowsePayload) =>
    request<LocalBrowseResponse>("/api/browse/books", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  fullScan: (limit?: number | null) =>
    request<{ started: boolean; limit: number | null }>("/api/scan/full", {
      method: "POST",
      body: JSON.stringify({ limit: limit || null }),
    }),
  startTopUp: (threshold: number) =>
    request<{
      started: boolean;
      activeChapters: number;
      threshold: number;
      reason: string;
    }>("/api/scan/top-up", {
      method: "POST",
      body: JSON.stringify({ limit: threshold }),
    }),
  updateTopUpThreshold: (threshold: number) =>
    request<{ threshold: number }>("/api/scan/top-up-threshold", {
      method: "POST",
      body: JSON.stringify({ threshold }),
    }),
  stopScan: () =>
    request<{ stopRequested: boolean; scanRunning: boolean }>("/api/scan/stop", {
      method: "POST",
    }),
  stopAllScans: () =>
    request<{ stopRequested: boolean; scanRunning: boolean }>("/api/scan/stop-all", {
      method: "POST",
    }),
  logs: (limit = 100) => request<LogEntry[]>(`/api/logs?limit=${limit}`),
  debugThreads: () => request<DebugThreads>("/api/debug/threads"),
  stopThread: (threadIdent: number) =>
    request<{ stopped: boolean; reason: string }>(
      `/api/debug/threads/${threadIdent}/stop`,
      { method: "POST" },
    ),
  libraryScan: () =>
    request<{
      books: number;
      chapters: number;
      error: string | null;
      root?: string;
      foldersSeen?: number;
      comicFilesSeen?: number;
    }>(
      "/api/scan/library",
      { method: "POST" },
    ),
  specificScan: (query: string) =>
    request<{ started: boolean; query: string }>("/api/scan/specific", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  specificPriorityScan: (query: string) =>
    request<{ started: boolean; query: string }>("/api/scan/specific-priority", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  downloadNow: (mangaId: number) =>
    request<{ paused: number; upgraded: number; mangaId: number }>(`/api/books/${mangaId}/download-now`, {
      method: "POST",
    }),
  updateSettings: (
    autoScanEveryDays: number,
    downloadConcurrency: number,
    browserConcurrency: number,
    imageDownloadWorkers: number,
    readerEngine: "playwright" | "selenium",
    komgaAutoEnabled: boolean,
    reorganizeOnDrain: boolean,
  ) =>
    request<Summary>("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        autoScanEveryDays,
        downloadConcurrency,
        browserConcurrency,
        imageDownloadWorkers,
        readerEngine,
        komgaAutoEnabled,
        reorganizeOnDrain,
      }),
    }),
  reorganizeLibrary: () =>
    request<{ started: boolean; running: boolean }>(
      "/api/library/reorganize",
      { method: "POST" },
    ),
  reorganizeStop: () =>
    request<{ stopped: boolean }>("/api/library/reorganize/stop", { method: "POST" }),
  reorganizeStatus: () =>
    request<{ running: boolean; result: Record<string, unknown> | null }>("/api/library/reorganize/status"),
  komgaCleanup: () =>
    request<{ deleted: number; komgaCreated: number; komgaScanned: number; errors: string[] }>(
      "/api/library/komga-cleanup",
      { method: "POST" },
    ),
  systemFlush: () => request<{ started: boolean }>("/api/system/flush", { method: "POST" }),
  systemFlushStop: () => request<{ stopped: boolean }>("/api/system/flush/stop", { method: "POST" }),
  systemFlushStatus: () => request<{ running: boolean; tasks: FlushTask[] }>("/api/system/flush/status"),
  pauseQueue: () =>
    request<{ queuePaused: boolean }>("/api/queue/pause", { method: "POST" }),
  resumeQueue: () =>
    request<{ queuePaused: boolean }>("/api/queue/resume", { method: "POST" }),
  enqueueMissing: () =>
    request<{ enqueued: number }>("/api/queue/enqueue-missing", { method: "POST" }),
  resetMissing: () =>
    request<{ mangaReset: number; chaptersReset: number; jobsRemoved: number }>(
      "/api/scan/reset-missing",
      { method: "POST" },
    ),
  deleteQueuedDownloads: () =>
    request<{ removed: number }>("/api/queue/queued", { method: "DELETE" }),
  deleteZeroPercentQueuedDownloads: () =>
    request<{ removed: number }>("/api/queue/queued-zero-percent", {
      method: "DELETE",
    }),
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
  importBook: (mangaId: number) =>
    request<{
      imported: boolean;
      libraryId: string;
      title: string;
    }>(`/api/komga/books/${mangaId}/import`, { method: "POST" }),
  quickScanAll: () =>
    request<{ scanned: boolean; libraryCount: number; deep: boolean }>(
      "/api/komga/quick-scan-all",
      { method: "POST" },
    ),
  importAllBooks: () =>
    request<{ started: boolean }>("/api/komga/import-all", { method: "POST" }),
  priorityScan: (payload: BrowseSearchPayload) =>
    request<{ started: boolean }>("/api/scan/priority", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
