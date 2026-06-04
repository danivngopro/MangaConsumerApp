import { useEffect, useState } from "react";
import { AlertTriangle, Check, RefreshCw, Search, Star, X } from "lucide-react";
import { api, DuplicateCandidate } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";

type StatusFilter = "all" | DuplicateCandidate["status"];

type RemoteGroup = {
  remote_manga_id: number;
  remote_title: string;
  remote_chapter_count: number;
  candidates: DuplicateCandidate[];
};

function groupRemoteCandidates(items: DuplicateCandidate[]): {
  remoteGroups: RemoteGroup[];
  localDups: DuplicateCandidate[];
} {
  const groupMap = new Map<number, RemoteGroup>();
  const localDups: DuplicateCandidate[] = [];

  for (const item of items) {
    if (item.candidate_kind === "local_local") {
      localDups.push(item);
    } else if (item.remote_manga_id != null) {
      const existing = groupMap.get(item.remote_manga_id);
      if (existing) {
        existing.candidates.push(item);
      } else {
        groupMap.set(item.remote_manga_id, {
          remote_manga_id: item.remote_manga_id,
          remote_title: item.remote_title,
          remote_chapter_count: item.remote_chapter_count,
          candidates: [item],
        });
      }
    }
  }

  return {
    remoteGroups: Array.from(groupMap.values()),
    localDups,
  };
}

function dominantStatus(candidates: DuplicateCandidate[]): DuplicateCandidate["status"] {
  if (candidates.some((c) => c.status === "pending")) return "pending";
  if (candidates.some((c) => c.status === "confirmed_exists")) return "confirmed_exists";
  if (candidates.some((c) => c.status === "confirmed_new")) return "confirmed_new";
  return "ignored";
}

export function DuplicatesPage({ loading, runAction }: SharedProps) {
  const [items, setItems] = useState<DuplicateCandidate[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");

  async function refreshDuplicates() {
    setItems(await api.duplicates());
  }

  async function scanLocalDuplicates() {
    await runAction("Scan local duplicates", api.libraryScan);
    await refreshDuplicates();
  }

  useEffect(() => {
    refreshDuplicates().catch(() => {});
  }, []);

  async function resolveOne(candidate: DuplicateCandidate, status: "confirmed_exists" | "confirmed_new" | "ignored") {
    const label =
      status === "confirmed_exists"
        ? `Use local folder for ${candidate.remote_title}`
        : status === "confirmed_new"
        ? `Download as new: ${candidate.remote_title}`
        : `Ignore duplicate: ${candidate.remote_title}`;
    await runAction(label, () => api.resolveDuplicate(candidate.id, status));
    await refreshDuplicates();
  }

  async function resolveGroupAll(group: RemoteGroup, status: "confirmed_new" | "ignored") {
    for (const c of group.candidates) {
      await api.resolveDuplicate(c.id, status);
    }
    await refreshDuplicates();
  }

  async function resolveGroupMain(group: RemoteGroup, mainFolder: string) {
    const label = `Set main book for: ${group.remote_title}`;
    await runAction(label, () => api.resolveGroupMain(group.remote_manga_id, mainFolder));
    await refreshDuplicates();
  }

  async function resolveLocalDup(candidate: DuplicateCandidate, status: "confirmed_exists" | "ignored") {
    await runAction(`Resolve local duplicate: ${candidate.local_title}`, () =>
      api.resolveDuplicate(candidate.id, status),
    );
    await refreshDuplicates();
  }

  const { remoteGroups, localDups } = groupRemoteCandidates(items);

  const filteredGroups = remoteGroups.filter(
    (g) => statusFilter === "all" || dominantStatus(g.candidates) === statusFilter,
  );
  const filteredLocalDups = localDups.filter(
    (item) => statusFilter === "all" || item.status === statusFilter,
  );

  const pending = remoteGroups.filter((g) => dominantStatus(g.candidates) === "pending").length
    + localDups.filter((d) => d.status === "pending").length;
  const confirmed = remoteGroups.filter((g) => dominantStatus(g.candidates) === "confirmed_exists").length;

  return (
    <>
      <div className="page-header">
        <div className="page-title-row">
          <h2>Duplicates</h2>
          {pending > 0 && <span className="tag tag-yellow">{pending} pending</span>}
        </div>
        <div className="page-actions">
          <button className="btn-primary btn-sm" onClick={scanLocalDuplicates} disabled={loading}>
            <Search size={13} /> Scan local duplicates
          </button>
          <button className="btn-ghost btn-sm" onClick={refreshDuplicates} disabled={loading}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      <div className="metrics-grid" style={{ marginBottom: 14 }}>
        <StatCard label="Pending" value={`${pending}`} />
        <StatCard label="Main set" value={`${confirmed}`} />
        <StatCard label="Total groups" value={`${remoteGroups.length + localDups.length}`} />
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="filter-row">
          {(["pending", "confirmed_exists", "confirmed_new", "ignored", "all"] as const).map((status) => (
            <button
              key={status}
              className={`chip ${statusFilter === status ? "active" : ""}`}
              onClick={() => setStatusFilter(status)}
            >
              {status.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </div>

      <div className="download-list">
        {filteredGroups.map((group) => (
          <RemoteGroupCard
            key={group.remote_manga_id}
            group={group}
            loading={loading}
            onSetMain={(folder) => resolveGroupMain(group, folder)}
            onDownloadNew={() => resolveGroupAll(group, "confirmed_new")}
            onIgnoreAll={() => resolveGroupAll(group, "ignored")}
            onUseExisting={(candidate) => resolveOne(candidate, "confirmed_exists")}
          />
        ))}

        {filteredLocalDups.map((item) => (
          <LocalDupRow
            key={item.id}
            item={item}
            loading={loading}
            onConfirm={() => resolveLocalDup(item, "confirmed_exists")}
            onIgnore={() => resolveLocalDup(item, "ignored")}
          />
        ))}

        {filteredGroups.length === 0 && filteredLocalDups.length === 0 && (
          <p className="empty">
            {statusFilter === "pending"
              ? "No duplicate decisions are waiting."
              : "No duplicate candidates match this filter."}
          </p>
        )}
      </div>
    </>
  );
}

function RemoteGroupCard({
  group,
  loading,
  onSetMain,
  onDownloadNew,
  onIgnoreAll,
  onUseExisting,
}: {
  group: RemoteGroup;
  loading: boolean;
  onSetMain: (folder: string) => void;
  onDownloadNew: () => void;
  onIgnoreAll: () => void;
  onUseExisting: (candidate: DuplicateCandidate) => void;
}) {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const status = dominantStatus(group.candidates);
  const isMulti = group.candidates.length > 1;

  const mainCandidate = group.candidates.find((c) => c.status === "confirmed_exists");
  const effectiveSelected = selectedFolder ?? mainCandidate?.local_folder ?? null;

  return (
    <div className={`download-item ${status === "pending" ? "active" : ""}`}>
      <div className="download-main" style={{ minWidth: 0 }}>
        <div className="download-title">
          <AlertTriangle size={14} />
          <span>Asura: {group.remote_title}</span>
          <span className={`tag ${status === "pending" ? "tag-yellow" : "tag-purple"}`}>
            {status.replace(/_/g, " ")}
          </span>
        </div>
        <div className="download-meta">
          <span>{group.remote_chapter_count} remote chapters</span>
          {isMulti && <span>{group.candidates.length} local matches</span>}
        </div>

        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
          {group.candidates.map((c) => {
            const isSelected = effectiveSelected === c.local_folder;
            const isMain = c.status === "confirmed_exists";
            return (
              <label
                key={c.id}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "8px 10px",
                  borderRadius: 6,
                  border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                  background: isSelected ? "var(--accent-dim, rgba(139,92,246,0.08))" : "transparent",
                  cursor: status === "pending" ? "pointer" : "default",
                }}
                onClick={() => {
                  if (status === "pending") setSelectedFolder(c.local_folder);
                }}
              >
                {status === "pending" && (
                  <input
                    type="radio"
                    name={`group-${group.remote_manga_id}`}
                    checked={isSelected}
                    onChange={() => setSelectedFolder(c.local_folder)}
                    style={{ marginTop: 2, flexShrink: 0 }}
                  />
                )}
                {isMain && <Star size={14} style={{ color: "var(--accent)", flexShrink: 0, marginTop: 2 }} />}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 500 }}>{c.local_title}</div>
                  <div className="muted" style={{ marginTop: 2 }}>
                    {c.local_chapter_count} local chapters &middot; {Math.round(Number(c.score) * 100)}% match
                  </div>
                  <div className="muted" style={{ overflowWrap: "anywhere", marginTop: 2 }}>{c.local_folder}</div>
                  {c.local_chapter_count < group.remote_chapter_count && (
                    <div className="muted" style={{ marginTop: 2 }}>
                      {group.remote_chapter_count - c.local_chapter_count} chapters missing
                    </div>
                  )}
                </div>
              </label>
            );
          })}
        </div>

        {isMulti && status === "pending" && effectiveSelected && (
          <div className="muted" style={{ marginTop: 8, fontSize: "0.82em" }}>
            {(() => {
              const main = group.candidates.find((c) => c.local_folder === effectiveSelected);
              const richest = group.candidates
                .filter((c) => c.local_folder !== effectiveSelected)
                .sort((a, b) => b.local_chapter_count - a.local_chapter_count)[0];
              if (main && richest && richest.local_chapter_count > main.local_chapter_count) {
                return `${richest.local_chapter_count - main.local_chapter_count} chapters will be transferred from "${richest.local_title}" to the main book before deleting.`;
              }
              return null;
            })()}
          </div>
        )}
      </div>

      <div className="modal-actions" style={{ justifyContent: "flex-end" }}>
        {status === "pending" && (
          <>
            {isMulti ? (
              <button
                className="btn-primary btn-sm"
                onClick={() => effectiveSelected && onSetMain(effectiveSelected)}
                disabled={loading || !effectiveSelected}
              >
                <Check size={12} /> Set as main
              </button>
            ) : (
              <button
                className="btn-primary btn-sm"
                onClick={() => {
                  const only = group.candidates[0];
                  if (only) onUseExisting(only);
                }}
                disabled={loading}
              >
                <Check size={12} /> Use this
              </button>
            )}
            <button className="btn-ghost btn-sm" onClick={onDownloadNew} disabled={loading}>
              <X size={12} /> Download new
            </button>
            <button className="btn-ghost btn-sm" onClick={onIgnoreAll} disabled={loading}>
              Ignore
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function LocalDupRow({
  item,
  loading,
  onConfirm,
  onIgnore,
}: {
  item: DuplicateCandidate;
  loading: boolean;
  onConfirm: () => void;
  onIgnore: () => void;
}) {
  const score = Math.round(Number(item.score || 0) * 100);
  return (
    <div className={`download-item ${item.status === "pending" ? "active" : ""}`}>
      <div className="download-main" style={{ minWidth: 0 }}>
        <div className="download-title">
          <AlertTriangle size={14} />
          <span>Local duplicate</span>
          <span className={`tag ${item.status === "pending" ? "tag-yellow" : "tag-purple"}`}>
            {item.status.replace(/_/g, " ")}
          </span>
        </div>
        <div className="download-meta">
          <span>Keep: {item.remote_title} ({item.remote_chapter_count} chapters)</span>
          <span>Duplicate: {item.local_title} ({item.local_chapter_count} chapters)</span>
          <span>{score}% match</span>
        </div>
        <div className="muted" style={{ marginTop: 6, overflowWrap: "anywhere" }}>{item.local_folder}</div>
        <div className="muted" style={{ marginTop: 4 }}>{item.reason}</div>
      </div>
      <div className="modal-actions" style={{ justifyContent: "flex-end" }}>
        {item.status === "pending" && (
          <>
            <button className="btn-primary btn-sm" onClick={onConfirm} disabled={loading}>
              <Check size={12} /> Confirm
            </button>
            <button className="btn-ghost btn-sm" onClick={onIgnore} disabled={loading}>
              Ignore
            </button>
          </>
        )}
      </div>
    </div>
  );
}
