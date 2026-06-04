import { useEffect, useState } from "react";
import { RefreshCw, Tags, UploadCloud } from "lucide-react";
import { api, MetadataCandidate } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";

export function MetadataPage({ loading, runAction }: SharedProps) {
  const [items, setItems] = useState<MetadataCandidate[]>([]);
  const [filter, setFilter] = useState<"all" | "unsynced" | "error" | "synced">("unsynced");
  const [syncProgress, setSyncProgress] = useState<{ current: number; total: number; title: string } | null>(null);

  async function refreshMetadata() {
    setItems(await api.metadataCandidates());
  }

  useEffect(() => {
    refreshMetadata().catch(() => {});
  }, []);

  async function syncAll() {
    const candidates = items.filter((item) => !item.metadata_synced_at || item.metadata_last_error);
    const targets = candidates.length ? candidates : items;
    setSyncProgress({ current: 0, total: targets.length, title: "Starting" });
    try {
      for (let index = 0; index < targets.length; index += 1) {
        const item = targets[index];
        setSyncProgress({ current: index, total: targets.length, title: item.title });
        await api.syncMetadata([item.id]);
        setSyncProgress({ current: index + 1, total: targets.length, title: item.title });
      }
      await refreshMetadata();
    } finally {
      setSyncProgress(null);
    }
  }

  async function syncOne(item: MetadataCandidate) {
    await runAction(`Sync metadata: ${item.title}`, () => api.syncMetadata([item.id]));
    await refreshMetadata();
  }

  const synced = items.filter((item) => item.metadata_synced_at && !item.metadata_last_error).length;
  const errors = items.filter((item) => item.metadata_last_error).length;
  const unsynced = items.filter((item) => !item.metadata_synced_at && !item.metadata_last_error).length;
  const filtered = items.filter((item) => {
    if (filter === "synced") return Boolean(item.metadata_synced_at && !item.metadata_last_error);
    if (filter === "error") return Boolean(item.metadata_last_error);
    if (filter === "unsynced") return !item.metadata_synced_at && !item.metadata_last_error;
    return true;
  });

  return (
    <>
      <div className="page-header">
        <div className="page-title-row">
          <h2>Metadata</h2>
          {errors > 0 && <span className="tag tag-red">{errors} errors</span>}
        </div>
        <div className="page-actions">
          <button className="btn-ghost btn-sm" onClick={refreshMetadata} disabled={loading}>
            <RefreshCw size={13} /> Refresh
          </button>
          <button className="btn-primary btn-sm" onClick={syncAll} disabled={loading || Boolean(syncProgress) || items.length === 0}>
            <UploadCloud size={13} /> Sync verified
          </button>
        </div>
      </div>

      <div className="metrics-grid" style={{ marginBottom: 14 }}>
        <StatCard label="Unsynced" value={`${unsynced}`} />
        <StatCard label="Synced" value={`${synced}`} />
        <StatCard label="Errors / review" value={`${errors}`} />
      </div>

      <div className="status-bar" style={{ marginBottom: 14, alignItems: "flex-start" }}>
        <span className="status-dot" style={{ marginTop: 7 }} />
        <span>
          Sync verified uses books already found by local library scan or confirmed duplicate matching, refreshes available Asura metadata including descriptions, then updates the matched Komga series. Run a library scan first if new local folders are missing here.
        </span>
      </div>

      {syncProgress && (
        <div className="metadata-sync-progress">
          <div className="total-bar-header">
            <span className="total-bar-label">Syncing metadata</span>
            <span className="total-bar-pct">
              {syncProgress.current} / {syncProgress.total}
            </span>
            <span className="total-bar-extra">{syncProgress.title}</span>
          </div>
          <div className="track">
            <div
              className="track-fill"
              style={{ width: `${syncProgress.total ? (syncProgress.current / syncProgress.total) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="filter-row">
          {(["unsynced", "error", "synced", "all"] as const).map((value) => (
            <button
              key={value}
              className={`chip ${filter === value ? "active" : ""}`}
              onClick={() => setFilter(value)}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      <div className="download-list">
        {filtered.map((item) => (
          <MetadataRow key={item.id} item={item} loading={loading} onSync={() => syncOne(item)} />
        ))}
        {filtered.length === 0 && <p className="empty">No metadata candidates match this filter.</p>}
      </div>
    </>
  );
}

function MetadataRow({ item, loading, onSync }: { item: MetadataCandidate; loading: boolean; onSync: () => void }) {
  const genres = (item.asura_genres || [])
    .map((genre) => (typeof genre === "string" ? genre : genre.name || genre.slug || ""))
    .filter(Boolean);
  return (
    <div className={`download-item ${item.metadata_last_error ? "active" : ""}`}>
      <div className="download-main" style={{ minWidth: 0 }}>
        <div className="download-title">
          <Tags size={14} />
          <span>{item.title}</span>
          {item.metadata_synced_at && !item.metadata_last_error && <span className="tag tag-purple">synced</span>}
          {item.metadata_last_error && <span className="tag tag-red">review</span>}
        </div>
        <div className="download-meta">
          {item.asura_type && <span>{item.asura_type}</span>}
          {item.asura_author && <span>Author: {item.asura_author}</span>}
          {item.asura_artist && <span>Artist: {item.asura_artist}</span>}
          {genres.length > 0 && <span>{genres.join(", ")}</span>}
        </div>
        {item.metadata_last_error && (
          <div className="muted" style={{ marginTop: 6, overflowWrap: "anywhere" }}>
            {item.metadata_last_error}
          </div>
        )}
        <div className="muted" style={{ marginTop: 4 }}>
          Last sync: {item.metadata_synced_at ? new Date(item.metadata_synced_at).toLocaleString() : "never"}
        </div>
      </div>
      <div className="modal-actions" style={{ justifyContent: "flex-end" }}>
        <button className="btn-ghost btn-sm" onClick={onSync} disabled={loading}>
          <UploadCloud size={12} /> Sync
        </button>
      </div>
    </div>
  );
}
