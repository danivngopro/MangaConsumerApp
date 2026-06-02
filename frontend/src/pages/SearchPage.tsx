import { FormEvent, useState } from "react";
import { BookOpen, ChevronDown, Search } from "lucide-react";
import {
  api,
  BrowseFilters,
  BrowseResult,
  BrowseSearchPayload,
} from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";

type Props = SharedProps & { browseFilters: BrowseFilters | null };

export function SearchPage({ browseFilters, loading, runAction }: Props) {
  const [browseSearch,      setBrowseSearch]      = useState("");
  const [browseStatus,      setBrowseStatus]      = useState("all");
  const [browseType,        setBrowseType]        = useState("all");
  const [browseSort,        setBrowseSort]        = useState("latest");
  const [browseOrder,       setBrowseOrder]       = useState("desc");
  const [browseAuthor,      setBrowseAuthor]      = useState("");
  const [browseArtist,      setBrowseArtist]      = useState("");
  const [browseMinChapters, setBrowseMinChapters] = useState(0);
  const [browseMaxChapters, setBrowseMaxChapters] = useState(0);
  const [browseGenres,      setBrowseGenres]      = useState<string[]>([]);
  const [hideExisting,      setHideExisting]      = useState(true);
  const [hideStrings,       setHideStrings]       = useState("");
  const [advancedOpen,      setAdvancedOpen]      = useState(false);

  const [results,      setResults]      = useState<BrowseResult[]>([]);
  const [total,        setTotal]        = useState(0);
  const [offset,       setOffset]       = useState(0);
  const [browseLoading,setBrowseLoading]= useState(false);
  const [browseStatus2,setBrowseStatus2]= useState("");

  function payload(off = 0): BrowseSearchPayload {
    return {
      search: browseSearch.trim(),
      genres: browseGenres,
      author: browseAuthor.trim(),
      artist: browseArtist.trim(),
      status: browseStatus,
      type:   browseType,
      sort:   browseSort,
      order:  browseOrder,
      minChapters: browseMinChapters,
      maxChapters: browseMaxChapters,
      limit: 24,
      offset: off,
    };
  }

  async function doSearch(event?: FormEvent<HTMLFormElement>, off = 0) {
    event?.preventDefault();
    setBrowseLoading(true);
    setBrowseStatus2("Searching Asura…");
    try {
      const res = await api.asuraSearch(payload(off));
      setResults(res.items);
      setTotal(res.total);
      setOffset(res.offset);
      setBrowseStatus2(`Found ${res.total.toLocaleString()} Asura books`);
    } catch (e) {
      setBrowseStatus2(e instanceof Error ? e.message : String(e));
    } finally {
      setBrowseLoading(false);
    }
  }

  function toggleGenre(slug: string) {
    setBrowseGenres((cur) =>
      cur.includes(slug) ? cur.filter((s) => s !== slug) : [...cur, slug],
    );
  }

  const hiddenStrings = hideStrings
    .split(/\r?\n|,/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);

  const visible = results.filter((item) => {
    if (hideExisting && item.is_existing) return false;
    if (hiddenStrings.some((h) => item.title.toLowerCase().includes(h))) return false;
    return true;
  });

  return (
    <>
      <div className="page-header">
        <div className="page-title-row">
          <h2>Asura Search</h2>
          {browseStatus2 && (
            <span className="tag tag-purple">{browseStatus2}</span>
          )}
        </div>
        {results.length > 0 && (
          <button
            className="btn-primary btn-sm"
            disabled={browseLoading || loading || results.length === 0}
            onClick={() =>
              runAction("Priority scan", () =>
                api.priorityScan(payload(offset)),
              )
            }
            title="Scan this result page and place missing chapters at front of queue."
          >
            Priority scan page
          </button>
        )}
      </div>

      {/* Search form */}
      <form className="browse-form" onSubmit={(e) => doSearch(e, 0)}>
        <input
          value={browseSearch}
          onChange={(e) => setBrowseSearch(e.target.value)}
          placeholder="Search Asura titles"
        />
        <select
          value={browseStatus}
          onChange={(e) => setBrowseStatus(e.target.value)}
          title="Filter by status."
        >
          {(browseFilters?.statuses ?? ["all", "ongoing", "completed", "hiatus", "dropped", "axed"]).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={browseType}
          onChange={(e) => setBrowseType(e.target.value)}
          title="Filter by type."
        >
          {(browseFilters?.types ?? ["all", "manhwa", "manhua", "manga"]).map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select
          value={browseSort}
          onChange={(e) => setBrowseSort(e.target.value)}
        >
          {(browseFilters?.sorts ?? ["latest", "popular", "rating", "title", "chapters"]).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={browseOrder}
          onChange={(e) => setBrowseOrder(e.target.value)}
        >
          <option value="desc">desc</option>
          <option value="asc">asc</option>
        </select>
        <button className="btn-primary" disabled={browseLoading}>
          <Search size={13} /> Search
        </button>
      </form>

      {/* Advanced filters toggle */}
      <div style={{ marginBottom: 12 }}>
        <button
          type="button"
          className="btn-ghost btn-sm"
          onClick={() => setAdvancedOpen((v) => !v)}
          style={{ gap: 6 }}
        >
          Filters
          <ChevronDown
            size={13}
            style={{
              transition: "transform 200ms",
              transform: advancedOpen ? "rotate(180deg)" : "rotate(0deg)",
            }}
          />
        </button>
      </div>

      {advancedOpen && (
        <div className="advanced-panel">
          <div className="adv-row">
            <div>
              <span className="field-label">Author</span>
              <input
                value={browseAuthor}
                onChange={(e) => setBrowseAuthor(e.target.value)}
                placeholder="Any author"
                list="author-opts"
              />
              <datalist id="author-opts">
                {(browseFilters?.authors ?? []).map((a) => <option key={a} value={a} />)}
              </datalist>
            </div>
            <div>
              <span className="field-label">Artist</span>
              <input
                value={browseArtist}
                onChange={(e) => setBrowseArtist(e.target.value)}
                placeholder="Any artist"
                list="artist-opts"
              />
              <datalist id="artist-opts">
                {(browseFilters?.artists ?? []).map((a) => <option key={a} value={a} />)}
              </datalist>
            </div>
            <div>
              <span className="field-label">Min episodes</span>
              <input
                type="number"
                min={0}
                value={browseMinChapters}
                onChange={(e) => setBrowseMinChapters(Number(e.target.value))}
                placeholder="0 = any"
              />
            </div>
            <div>
              <span className="field-label">Max episodes</span>
              <input
                type="number"
                min={0}
                value={browseMaxChapters}
                onChange={(e) => setBrowseMaxChapters(Number(e.target.value))}
                placeholder="0 = no limit"
              />
            </div>
          </div>

          <div className="filter-row">
            <label>
              <input
                type="checkbox"
                checked={hideExisting}
                onChange={(e) => setHideExisting(e.target.checked)}
              />
              Hide books already in Komga
            </label>
            <div className="hide-textarea-wrap">
              <span className="field-label">Hide titles containing</span>
              <textarea
                value={hideStrings}
                onChange={(e) => setHideStrings(e.target.value)}
                placeholder="academy, regression, necromancer"
                style={{ width: 260, height: 52 }}
              />
            </div>
          </div>

          {(browseFilters?.genres ?? []).length > 0 && (
            <div>
              <span className="field-label">Genres</span>
              <div className="genre-cloud">
                {(browseFilters?.genres ?? []).map((g) => (
                  <button
                    key={g.slug}
                    type="button"
                    className={`chip${browseGenres.includes(g.slug) ? " on" : ""}`}
                    onClick={() => toggleGenre(g.slug)}
                  >
                    {g.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Results header */}
      {results.length > 0 && (
        <div className="results-bar">
          <span className="results-count">
            Showing {visible.length} of {results.length} loaded
            {total ? ` · ${total.toLocaleString()} total` : ""}
          </span>
          <div className="results-nav">
            <button
              className="btn-ghost btn-sm"
              disabled={browseLoading || offset === 0}
              onClick={() => doSearch(undefined, Math.max(0, offset - 24))}
            >
              Previous
            </button>
            <span className="muted" style={{ padding: "0 4px" }}>
              {Math.floor(offset / 24) + 1}
            </span>
            <button
              className="btn-ghost btn-sm"
              disabled={browseLoading || offset + 24 >= total}
              onClick={() => doSearch(undefined, offset + 24)}
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Results grid */}
      {browseLoading && <p className="empty">Searching…</p>}
      {!browseLoading && visible.length > 0 && (
        <div className="browse-list">
          {visible.map((item) => (
            <BrowseItem
              key={item.id}
              item={item}
              loading={loading || browseLoading}
              onAdd={() =>
                runAction(`Add: ${item.title}`, () =>
                  api.specificPriorityScan(item.url),
                )
              }
            />
          ))}
        </div>
      )}
      {!browseLoading && results.length > 0 && visible.length === 0 && (
        <p className="empty">All results hidden by filters.</p>
      )}
      {!browseLoading && results.length === 0 && (
        <p className="empty">Search Asura to see results here.</p>
      )}
    </>
  );
}

/* ── Browse result item ───────────────────────────────────────── */
function BrowseItem({
  item,
  loading,
  onAdd,
}: {
  item: BrowseResult;
  loading: boolean;
  onAdd: () => void;
}) {
  return (
    <div className="browse-item">
      {item.cover_url ? (
        <img className="browse-cover" src={item.cover_url} alt="" loading="lazy" />
      ) : (
        <div className="cover-ph"><BookOpen size={18} /></div>
      )}

      <div className="browse-info">
        <a href={item.url} target="_blank" rel="noreferrer">
          {item.title}
        </a>
        <span>
          {[item.status, item.type, `${item.chapter_count} ep`].filter(Boolean).join(" · ")}
        </span>
        <small>{item.genres.map((g) => g.name).join(", ") || "No genres"}</small>
        {item.local_folder && <small>{item.local_folder}</small>}
      </div>

      <div className="browse-counts">
        <StatCard label="On disk" value={`${item.local_chapter_count}`} />
        <StatCard label="Asura"   value={`${item.chapter_count}`} />
        <StatCard label="Missing" value={`${item.missing_count}`} />
      </div>

      <button
        className="btn-primary btn-sm"
        onClick={onAdd}
        disabled={loading}
        title="Scan this book and queue missing chapters."
      >
        Add
      </button>
    </div>
  );
}
