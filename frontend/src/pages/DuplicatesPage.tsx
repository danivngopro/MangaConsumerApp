import { useEffect, useState } from "react";
import { AlertTriangle, Check, RefreshCw, Trash2, X } from "lucide-react";
import { api, DuplicateCandidate } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";

export function DuplicatesPage({ loading, runAction }: SharedProps) {
  const [items, setItems] = useState<DuplicateCandidate[]>([]);
  const [statusFilter, setStatusFilter] = useState<"all" | DuplicateCandidate["status"]>("pending");

  async function refreshDuplicates() {
    setItems(await api.duplicates());
  }

  useEffect(() => {
    refreshDuplicates().catch(() => {});
  }, []);

  async function resolve(candidate: DuplicateCandidate, status: "confirmed_exists" | "confirmed_new" | "ignored") {
    const label = candidate.candidate_kind === "local_local"
      ? `Ignore local duplicate: ${candidate.local_title}`
      : status === "confirmed_exists"
      ? `Use local folder for ${candidate.remote_title}`
      : status === "confirmed_new"
      ? `Download as new: ${candidate.remote_title}`
      : `Ignore duplicate: ${candidate.remote_title}`;
    await runAction(label, () => api.resolveDuplicate(candidate.id, status));
    await refreshDuplicates();
  }

  async function deleteLocal(candidate: DuplicateCandidate) {
    if (!window.confirm(`Delete this local duplicate folder and its Komga library?\n\n${candidate.local_folder}`)) return;
    await runAction(`Delete duplicate: ${candidate.local_title}`, () => api.deleteDuplicateLocal(candidate.id));
    await refreshDuplicates();
  }

  const filtered = items.filter((item) => statusFilter === "all" || item.status === statusFilter);
  const pending = items.filter((item) => item.status === "pending").length;
  const confirmed = items.filter((item) => item.status === "confirmed_exists").length;

  return (
    <>
      <div className="page-header">
        <div className="page-title-row">
          <h2>Duplicates</h2>
          {pending > 0 && <span className="tag tag-yellow">{pending} pending</span>}
        </div>
        <div className="page-actions">
          <button className="btn-ghost btn-sm" onClick={refreshDuplicates} disabled={loading}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      <div className="metrics-grid" style={{ marginBottom: 14 }}>
        <StatCard label="Pending" value={`${pending}`} />
        <StatCard label="Use existing" value={`${confirmed}`} />
        <StatCard label="Total candidates" value={`${items.length}`} />
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="filter-row">
          {(["pending", "confirmed_exists", "confirmed_new", "ignored", "all"] as const).map((status) => (
            <button
              key={status}
              className={`chip ${statusFilter === status ? "active" : ""}`}
              onClick={() => setStatusFilter(status)}
            >
              {status.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      <div className="download-list">
        {filtered.map((item) => (
          <DuplicateRow
            key={item.id}
            item={item}
            loading={loading}
            onUseExisting={() => resolve(item, "confirmed_exists")}
            onDownloadNew={() => resolve(item, "confirmed_new")}
            onIgnore={() => resolve(item, "ignored")}
            onDelete={() => deleteLocal(item)}
          />
        ))}
        {filtered.length === 0 && (
          <p className="empty">
            {statusFilter === "pending" ? "No duplicate decisions are waiting." : "No duplicate candidates match this filter."}
          </p>
        )}
      </div>
    </>
  );
}

function DuplicateRow({
  item,
  loading,
  onUseExisting,
  onDownloadNew,
  onIgnore,
  onDelete,
}: {
  item: DuplicateCandidate;
  loading: boolean;
  onUseExisting: () => void;
  onDownloadNew: () => void;
  onIgnore: () => void;
  onDelete: () => void;
}) {
  const score = Math.round(Number(item.score || 0) * 100);
  return (
    <div className={`download-item ${item.status === "pending" ? "active" : ""}`}>
      <div className="download-main" style={{ minWidth: 0 }}>
        <div className="download-title">
          <AlertTriangle size={14} />
          <span>{item.candidate_kind === "local_local" ? "Existing local duplicate" : item.remote_title}</span>
          <span className={`tag ${item.status === "pending" ? "tag-yellow" : "tag-purple"}`}>
            {item.status.replace("_", " ")}
          </span>
        </div>
        <div className="download-meta">
          {item.candidate_kind === "local_local" && <span>Keep: {item.remote_title}</span>}
          <span>{item.candidate_kind === "local_local" ? `Delete candidate: ${item.local_title}` : `Local: ${item.local_title}`}</span>
          <span>{item.local_chapter_count} local / {item.remote_chapter_count} remote</span>
          <span>{score}% match</span>
        </div>
        <div className="muted" style={{ marginTop: 6, overflowWrap: "anywhere" }}>
          {item.local_folder}
        </div>
        <div className="muted" style={{ marginTop: 4 }}>
          {item.reason}
        </div>
      </div>
      <div className="modal-actions" style={{ justifyContent: "flex-end" }}>
        {item.status === "pending" && (
          <>
            {item.candidate_kind === "remote_local" && (
              <>
                <button className="btn-primary btn-sm" onClick={onUseExisting} disabled={loading}>
                  <Check size={12} /> Exists
                </button>
                <button className="btn-ghost btn-sm" onClick={onDownloadNew} disabled={loading}>
                  <X size={12} /> New
                </button>
              </>
            )}
            <button className="btn-ghost btn-sm" onClick={onIgnore} disabled={loading}>
              Ignore
            </button>
          </>
        )}
        <button className="btn-ghost btn-sm danger" onClick={onDelete} disabled={loading}>
          <Trash2 size={12} /> Delete local
        </button>
      </div>
    </div>
  );
}
