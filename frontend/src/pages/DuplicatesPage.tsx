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

type RemoteChoice =
  | { kind: "main"; folder: string }
  | { kind: "existing"; candidateId: number }
  | { kind: "new" }
  | { kind: "ignore" };

type LocalChoice =
  | { kind: "main"; folder: string }
  | { kind: "ignore" };

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

  return { remoteGroups: Array.from(groupMap.values()), localDups };
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
  const [remoteChoices, setRemoteChoices] = useState<Record<number, RemoteChoice>>({});
  const [localChoices, setLocalChoices] = useState<Record<number, LocalChoice>>({});
  const [bulkProgress, setBulkProgress] = useState<{ current: number; total: number } | null>(null);

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

  function stageRemoteChoice(groupId: number, choice: RemoteChoice | null) {
    setRemoteChoices((current) => {
      const next = { ...current };
      if (choice) next[groupId] = choice;
      else delete next[groupId];
      return next;
    });
  }

  function stageLocalChoice(candidateId: number, choice: LocalChoice | null) {
    setLocalChoices((current) => {
      const next = { ...current };
      if (choice) next[candidateId] = choice;
      else delete next[candidateId];
      return next;
    });
  }

  const { remoteGroups, localDups } = groupRemoteCandidates(items);

  async function saveSelectedChoices() {
    const stagedRemote = remoteGroups
      .map((group) => ({ group, choice: remoteChoices[group.remote_manga_id] }))
      .filter((item): item is { group: RemoteGroup; choice: RemoteChoice } => Boolean(item.choice));
    const stagedLocal = localDups
      .map((candidate) => ({ candidate, choice: localChoices[candidate.id] }))
      .filter((item): item is { candidate: DuplicateCandidate; choice: LocalChoice } => Boolean(item.choice));
    const total = stagedRemote.length + stagedLocal.length;
    if (total === 0) return;

    setBulkProgress({ current: 0, total });
    await runAction("Save duplicate choices", async () => {
      let done = 0;
      for (const { group, choice } of stagedRemote) {
        if (choice.kind === "main") {
          await api.resolveGroupMain(group.remote_manga_id, choice.folder);
        } else if (choice.kind === "existing") {
          await api.resolveDuplicate(choice.candidateId, "confirmed_exists");
        } else {
          const status = choice.kind === "new" ? "confirmed_new" : "ignored";
          for (const candidate of group.candidates) {
            await api.resolveDuplicate(candidate.id, status);
          }
        }
        done += 1;
        setBulkProgress({ current: done, total });
      }

      for (const { candidate, choice } of stagedLocal) {
        if (choice.kind === "main") {
          await api.resolveLocalMain(candidate.id, choice.folder);
        } else {
          await api.resolveDuplicate(candidate.id, "ignored");
        }
        done += 1;
        setBulkProgress({ current: done, total });
      }
      return { saved: total };
    });

    setRemoteChoices({});
    setLocalChoices({});
    setBulkProgress(null);
    await refreshDuplicates();
  }

  const filteredGroups = remoteGroups.filter(
    (group) => statusFilter === "all" || dominantStatus(group.candidates) === statusFilter,
  );
  const filteredLocalDups = localDups.filter(
    (item) => statusFilter === "all" || item.status === statusFilter,
  );

  const pending = remoteGroups.filter((group) => dominantStatus(group.candidates) === "pending").length
    + localDups.filter((item) => item.status === "pending").length;
  const confirmed = remoteGroups.filter((group) => dominantStatus(group.candidates) === "confirmed_exists").length;
  const stagedCount = Object.keys(remoteChoices).length + Object.keys(localChoices).length;

  return (
    <>
      <div className="page-header">
        <div className="page-title-row">
          <h2>Duplicates</h2>
          {pending > 0 && <span className="tag tag-yellow">{pending} pending</span>}
        </div>
        <div className="page-actions">
          <button className="btn-primary btn-sm" onClick={saveSelectedChoices} disabled={loading || stagedCount === 0}>
            <Check size={13} /> Save selected ({stagedCount})
          </button>
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
        <StatCard label="Staged choices" value={`${stagedCount}`} />
        <StatCard label="Total groups" value={`${remoteGroups.length + localDups.length}`} />
      </div>

      {bulkProgress && (
        <div className="metadata-sync-progress">
          <div className="total-bar-header">
            <span className="total-bar-label">Saving duplicate choices</span>
            <span className="total-bar-pct">{bulkProgress.current} / {bulkProgress.total}</span>
          </div>
          <div className="track">
            <div
              className="track-fill"
              style={{ width: `${bulkProgress.total ? (bulkProgress.current / bulkProgress.total) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

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
            choice={remoteChoices[group.remote_manga_id] ?? null}
            onStageChoice={(choice) => stageRemoteChoice(group.remote_manga_id, choice)}
          />
        ))}

        {filteredLocalDups.map((item) => (
          <LocalDupRow
            key={item.id}
            item={item}
            loading={loading}
            choice={localChoices[item.id] ?? null}
            onStageChoice={(choice) => stageLocalChoice(item.id, choice)}
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
  choice,
  onStageChoice,
}: {
  group: RemoteGroup;
  loading: boolean;
  choice: RemoteChoice | null;
  onStageChoice: (choice: RemoteChoice | null) => void;
}) {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const status = dominantStatus(group.candidates);
  const isMulti = group.candidates.length > 1;
  const mainCandidate = group.candidates.find((candidate) => candidate.status === "confirmed_exists");
  const stagedMain = choice?.kind === "main" ? choice.folder : null;
  const effectiveSelected = stagedMain ?? selectedFolder ?? mainCandidate?.local_folder ?? null;
  const stagedLabel = choice ? choice.kind.replace("existing", "use existing") + " staged" : "";

  return (
    <div className={`download-item ${status === "pending" ? "active" : ""}`}>
      <div className="download-main" style={{ minWidth: 0 }}>
        <div className="download-title">
          <AlertTriangle size={14} />
          <span>Asura: {group.remote_title}</span>
          <span className={`tag ${status === "pending" ? "tag-yellow" : "tag-purple"}`}>
            {status.replace(/_/g, " ")}
          </span>
          {choice && <span className="tag tag-purple">{stagedLabel}</span>}
        </div>
        <div className="download-meta">
          <span>{group.remote_chapter_count} remote chapters</span>
          {isMulti && <span>{group.candidates.length} local matches</span>}
        </div>

        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
          {group.candidates.map((candidate) => {
            const isSelected =
              effectiveSelected === candidate.local_folder ||
              (choice?.kind === "existing" && choice.candidateId === candidate.id);
            return (
              <label
                key={candidate.id}
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
                  if (status !== "pending") return;
                  setSelectedFolder(candidate.local_folder);
                  onStageChoice(isMulti
                    ? { kind: "main", folder: candidate.local_folder }
                    : { kind: "existing", candidateId: candidate.id });
                }}
              >
                {status === "pending" && (
                  <input
                    type="radio"
                    name={`group-${group.remote_manga_id}`}
                    checked={isSelected}
                    onChange={() => {
                      setSelectedFolder(candidate.local_folder);
                      onStageChoice(isMulti
                        ? { kind: "main", folder: candidate.local_folder }
                        : { kind: "existing", candidateId: candidate.id });
                    }}
                    style={{ marginTop: 2, flexShrink: 0 }}
                  />
                )}
                {candidate.status === "confirmed_exists" && (
                  <Star size={14} style={{ color: "var(--accent)", flexShrink: 0, marginTop: 2 }} />
                )}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 500 }}>{candidate.local_title}</div>
                  <div className="muted" style={{ marginTop: 2 }}>
                    {candidate.local_chapter_count} local chapters &middot; {Math.round(Number(candidate.score) * 100)}% match
                  </div>
                  <div className="muted" style={{ overflowWrap: "anywhere", marginTop: 2 }}>{candidate.local_folder}</div>
                  {candidate.local_chapter_count < group.remote_chapter_count && (
                    <div className="muted" style={{ marginTop: 2 }}>
                      {group.remote_chapter_count - candidate.local_chapter_count} chapters missing
                    </div>
                  )}
                </div>
              </label>
            );
          })}
        </div>
      </div>

      <div className="modal-actions" style={{ justifyContent: "flex-end" }}>
        {status === "pending" && (
          <>
            <button
              className="btn-primary btn-sm"
              onClick={() => {
                const only = group.candidates[0];
                if (isMulti && effectiveSelected) onStageChoice({ kind: "main", folder: effectiveSelected });
                if (!isMulti && only) onStageChoice({ kind: "existing", candidateId: only.id });
              }}
              disabled={loading || (isMulti && !effectiveSelected)}
            >
              <Check size={12} /> {isMulti ? "Stage main" : "Stage use"}
            </button>
            <button className="btn-ghost btn-sm" onClick={() => onStageChoice({ kind: "new" })} disabled={loading}>
              <X size={12} /> Stage new
            </button>
            <button className="btn-ghost btn-sm" onClick={() => onStageChoice({ kind: "ignore" })} disabled={loading}>
              Stage ignore
            </button>
            {choice && (
              <button className="btn-ghost btn-sm" onClick={() => onStageChoice(null)} disabled={loading}>
                Clear
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function LocalDupRow({
  item,
  loading,
  choice,
  onStageChoice,
}: {
  item: DuplicateCandidate;
  loading: boolean;
  choice: LocalChoice | null;
  onStageChoice: (choice: LocalChoice | null) => void;
}) {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const score = Math.round(Number(item.score || 0) * 100);
  const books = [
    { title: item.remote_title, folder: item.remote_folder, chapters: item.remote_chapter_count, folderMissing: item.remote_folder == null },
    { title: item.local_title, folder: item.local_folder, chapters: item.local_chapter_count, folderMissing: false },
  ];
  const stagedMain = choice?.kind === "main" ? choice.folder : null;
  const effectiveSelected = stagedMain ?? selectedFolder ?? (item.remote_folder ?? item.local_folder);
  const canResolve = item.remote_folder != null;

  return (
    <div className={`download-item ${item.status === "pending" ? "active" : ""}`}>
      <div className="download-main" style={{ minWidth: 0 }}>
        <div className="download-title">
          <AlertTriangle size={14} />
          <span>Local duplicate</span>
          <span className={`tag ${item.status === "pending" ? "tag-yellow" : "tag-purple"}`}>
            {item.status.replace(/_/g, " ")}
          </span>
          {choice && <span className="tag tag-purple">{choice.kind} staged</span>}
          <span className="muted" style={{ fontSize: "0.82em" }}>{score}% match</span>
        </div>

        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
          {item.remote_folder == null && item.status === "pending" && (
            <div className="muted" style={{ marginTop: 6, fontSize: "0.82em" }}>
              Run "Scan local duplicates" to load both folder paths and enable picking a main book.
            </div>
          )}
          {books.map((book) => {
            const bookFolder = book.folder ?? `__missing__${book.title}`;
            const isSelected = effectiveSelected === bookFolder || effectiveSelected === book.folder;
            return (
              <label
                key={bookFolder}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "8px 10px",
                  borderRadius: 6,
                  border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                  background: isSelected ? "var(--accent-dim, rgba(139,92,246,0.08))" : "transparent",
                  cursor: item.status === "pending" ? "pointer" : "default",
                }}
                onClick={() => {
                  if (item.status === "pending" && book.folder) {
                    setSelectedFolder(book.folder);
                    onStageChoice({ kind: "main", folder: book.folder });
                  }
                }}
              >
                {item.status === "pending" && (
                  <input
                    type="radio"
                    name={`local-dup-${item.id}`}
                    checked={isSelected}
                    onChange={() => {
                      if (book.folder) {
                        setSelectedFolder(book.folder);
                        onStageChoice({ kind: "main", folder: book.folder });
                      }
                    }}
                    disabled={book.folderMissing}
                    style={{ marginTop: 2, flexShrink: 0 }}
                  />
                )}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 500 }}>{book.title}</div>
                  <div className="muted" style={{ marginTop: 2 }}>{book.chapters} chapters</div>
                  <div className="muted" style={{ overflowWrap: "anywhere", marginTop: 2 }}>
                    {book.folderMissing ? <em>folder path unknown - re-scan to load</em> : book.folder}
                  </div>
                </div>
              </label>
            );
          })}
        </div>

        <div className="muted" style={{ marginTop: 6 }}>{item.reason}</div>
      </div>

      <div className="modal-actions" style={{ justifyContent: "flex-end" }}>
        {item.status === "pending" && (
          <>
            <button
              className="btn-primary btn-sm"
              onClick={() => effectiveSelected && onStageChoice({ kind: "main", folder: effectiveSelected })}
              disabled={loading || !effectiveSelected || (!canResolve && !item.local_folder)}
            >
              <Check size={12} /> {canResolve ? "Stage main" : "Stage keep"}
            </button>
            <button className="btn-ghost btn-sm" onClick={() => onStageChoice({ kind: "ignore" })} disabled={loading}>
              Stage ignore
            </button>
            {choice && (
              <button className="btn-ghost btn-sm" onClick={() => onStageChoice(null)} disabled={loading}>
                Clear
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
