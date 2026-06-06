import { FormEvent, useEffect, useMemo, useState } from "react";
import { BookCheck, BookOpen, ExternalLink, Filter, Library, Play, RotateCcw, Search, X } from "lucide-react";
import { api, Book, BrowseFilters, BookDetail, LocalBrowsePayload } from "../api";
import { StatCard } from "../components/shared";
import type { SharedProps } from "../App";

type Props = SharedProps & { browseFilters: BrowseFilters | null };

const PAGE_SIZE = 36;
const CHAPTER_PAGE_SIZE = 10;

export function BrowsePage({ browseFilters, summary, loading }: Props) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [type, setType] = useState("all");
  const [sort, setSort] = useState("title");
  const [order, setOrder] = useState("asc");
  const [minChapters, setMinChapters] = useState(0);
  const [maxChapters, setMaxChapters] = useState(0);
  const [genres, setGenres] = useState<string[]>([]);
  const [items, setItems] = useState<Book[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [selected, setSelected] = useState<BookDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [chapterPage, setChapterPage] = useState(0);

  function payload(off = 0): LocalBrowsePayload {
    return {
      search: search.trim(),
      genres,
      status,
      type,
      sort,
      order,
      minChapters,
      maxChapters,
      limit: PAGE_SIZE,
      offset: off,
    };
  }

  async function load(off = 0, event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setBusy(true);
    setStatusText("Loading library...");
    try {
      const result = await api.browseBooks(payload(off));
      setItems(result.items);
      setTotal(result.total);
      setOffset(result.offset);
      setStatusText(`${result.total.toLocaleString()} local books`);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function openBook(book: Book) {
    setDetailLoading(true);
    setChapterPage(0);
    try {
      setSelected(await api.bookDetail(book.id));
    } finally {
      setDetailLoading(false);
    }
  }

  async function refreshSelected(mangaId: number) {
    setSelected(await api.bookDetail(mangaId));
  }

  async function markAllUnread() {
    if (!window.confirm("Mark every linked Komga series in this library as unread?")) return;
    setBusy(true);
    setStatusText("Marking all Komga chapters unread...");
    try {
      const result = await api.markAllKomgaUnread();
      setStatusText(`Marked ${result.markedSeries} Komga series unread`);
      if (selected) {
        await refreshSelected(selected.id);
      }
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function markLowProgressUnread() {
    if (!window.confirm("For every Komga library, mark any series with fewer than 30 read or reading chapters as unread?")) return;
    setBusy(true);
    setStatusText("Checking Komga read progress...");
    try {
      const result = await api.markLowProgressKomgaUnread(30);
      setStatusText(`Marked ${result.seriesMarkedUnread} of ${result.seriesChecked} Komga series unread`);
      if (selected) {
        await refreshSelected(selected.id);
      }
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  function toggleGenre(slug: string) {
    setGenres((current) => (
      current.includes(slug) ? current.filter((item) => item !== slug) : [...current, slug]
    ));
  }

  useEffect(() => {
    load(0).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const activeFilters = [
    search && "name",
    status !== "all" && status,
    type !== "all" && type,
    genres.length > 0 && `${genres.length} genres`,
    minChapters > 0 && `min ${minChapters}`,
    maxChapters > 0 && `max ${maxChapters}`,
  ].filter(Boolean);

  return (
    <div className="browse-page">
      <div className="page-header browse-head">
        <div className="page-title-row">
          <h2>Browse</h2>
          {statusText && <span className="tag tag-purple">{statusText}</span>}
          {activeFilters.length > 0 && <span className="tag tag-yellow">{activeFilters.join(" / ")}</span>}
        </div>
        <div className="page-actions">
          <button type="button" className="btn-ghost" disabled={busy || loading} onClick={markLowProgressUnread}>
            <RotateCcw size={14} /> Unread if &lt;30 active
          </button>
          <button type="button" className="btn-ghost" disabled={busy || loading} onClick={markAllUnread}>
            <RotateCcw size={14} /> Mark all unread
          </button>
        </div>
      </div>

      <form className="library-filter-panel" onSubmit={(event) => load(0, event)}>
        <div className="library-search">
          <Search size={15} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter by title, author, artist, or folder" />
        </div>
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          {(browseFilters?.statuses ?? ["all", "ongoing", "completed", "hiatus", "dropped", "axed"]).map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <select value={type} onChange={(event) => setType(event.target.value)}>
          {(browseFilters?.types ?? ["all", "manhwa", "manhua", "manga"]).map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <select value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="title">title</option>
          <option value="chapters">chapters</option>
          <option value="rating">rating</option>
          <option value="missing">missing</option>
          <option value="updated">updated</option>
        </select>
        <select value={order} onChange={(event) => setOrder(event.target.value)}>
          <option value="asc">asc</option>
          <option value="desc">desc</option>
        </select>
        <input type="number" min={0} value={minChapters} onChange={(event) => setMinChapters(Number(event.target.value))} title="Minimum local chapters" />
        <input type="number" min={0} value={maxChapters} onChange={(event) => setMaxChapters(Number(event.target.value))} title="Maximum local chapters" />
        <button className="btn-primary" disabled={busy || loading}>
          <Filter size={13} /> Apply
        </button>
      </form>

      {(browseFilters?.genres ?? []).length > 0 && (
        <div className="browse-genre-strip">
          {(browseFilters?.genres ?? []).map((genre) => (
            <button
              key={genre.slug}
              type="button"
              className={`chip${genres.includes(genre.slug) ? " on" : ""}`}
              onClick={() => toggleGenre(genre.slug)}
            >
              {genre.name}
            </button>
          ))}
        </div>
      )}

      <div className="library-results-bar">
        <span>Showing {items.length} of {total.toLocaleString()}</span>
        <div className="results-nav">
          <button className="btn-ghost btn-sm" disabled={busy || offset === 0} onClick={() => load(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
          <span className="muted">{Math.floor(offset / PAGE_SIZE) + 1}</span>
          <button className="btn-ghost btn-sm" disabled={busy || offset + PAGE_SIZE >= total} onClick={() => load(offset + PAGE_SIZE)}>Next</button>
        </div>
      </div>

      {busy && <p className="empty">Loading local books...</p>}
      {!busy && items.length === 0 && <p className="empty">No local books match these filters. Run a library scan first if the list is empty.</p>}
      {!busy && items.length > 0 && (
        <div className="library-grid">
          {items.map((book) => (
            <button key={book.id} className="library-book" onClick={() => openBook(book)}>
              {book.cover_url ? <img src={book.cover_url} alt="" loading="lazy" /> : <span className="cover-ph"><BookOpen size={20} /></span>}
              <span className="library-book-main">
                <strong>{book.title}</strong>
                <span>{[book.status, book.asura_type, `${book.local_chapter_count} chapters`].filter(Boolean).join(" / ")}</span>
                <span className="library-book-genres">
                  {genreNames(book).slice(0, 4).map((genre) => <em key={genre}>{genre}</em>)}
                  {genreNames(book).length === 0 && <small>No genre metadata</small>}
                </span>
              </span>
              <span className="library-book-stats">
                <span>{book.missing_count} missing</span>
                {book.asura_rating != null && <span>{book.asura_rating} rating</span>}
              </span>
            </button>
          ))}
        </div>
      )}

      {(selected || detailLoading) && (
        <BookModal
          book={selected}
          komgaUrl={summary.komgaPublicUrl || summary.komgaUrl}
          loading={detailLoading}
          chapterPage={chapterPage}
          setChapterPage={setChapterPage}
          onBookChanged={refreshSelected}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

function BookModal({
  book,
  komgaUrl,
  loading,
  chapterPage,
  setChapterPage,
  onBookChanged,
  onClose,
}: {
  book: BookDetail | null;
  komgaUrl: string;
  loading: boolean;
  chapterPage: number;
  setChapterPage: (page: number) => void;
  onBookChanged: (mangaId: number) => Promise<void>;
  onClose: () => void;
}) {
  const [readThroughChapter, setReadThroughChapter] = useState("");
  const [readThroughBusy, setReadThroughBusy] = useState(false);
  const [readThroughStatus, setReadThroughStatus] = useState("");
  const chapters = book?.chapters ?? [];
  const chapterPages = Math.max(1, Math.ceil(chapters.length / CHAPTER_PAGE_SIZE));
  const pageChapters = useMemo(
    () => chapters.slice(chapterPage * CHAPTER_PAGE_SIZE, chapterPage * CHAPTER_PAGE_SIZE + CHAPTER_PAGE_SIZE),
    [chapters, chapterPage],
  );
  const komgaSeriesUrl = book?.komga_series_id && komgaUrl ? `${komgaUrl.replace(/\/$/, "")}/series/${book.komga_series_id}` : null;

  async function markReadThrough(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!book) return;
    const chapterNumber = Number(readThroughChapter);
    if (!Number.isFinite(chapterNumber) || readThroughChapter.trim() === "") {
      setReadThroughStatus("Enter a chapter number.");
      return;
    }
    setReadThroughBusy(true);
    setReadThroughStatus("Marking chapters read...");
    try {
      const result = await api.markBookReadThrough(book.id, chapterNumber);
      setReadThroughStatus(`Marked ${result.marked} chapters read`);
      await onBookChanged(book.id);
    } catch (error) {
      setReadThroughStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setReadThroughBusy(false);
    }
  }

  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal browse-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div className="browse-modal-title">
            <Library size={18} />
            <div>
              <h2>{book?.title ?? "Loading book..."}</h2>
              <p>{book?.local_folder || "Local folder unavailable"}</p>
            </div>
          </div>
          <button className="btn-ghost btn-sm" onClick={onClose}><X size={13} /> Close</button>
        </div>

        {loading || !book ? (
          <p className="empty">Loading details...</p>
        ) : (
          <>
            <div className="browse-modal-grid">
              <div className="browse-cover-large">
                {book.cover_url ? <img src={book.cover_url} alt="" /> : <BookOpen size={38} />}
              </div>
              <div className="browse-summary">
                <a className="browse-komga-title" href={komgaSeriesUrl || undefined} target="_blank" rel="noreferrer" aria-disabled={!komgaSeriesUrl}>
                  {book.title}
                  {komgaSeriesUrl && <ExternalLink size={14} />}
                </a>
                <p>{book.asura_description || "No Asura description is stored yet. Use Metadata / Sync verified to refresh Asura metadata for verified local matches."}</p>
                <div className="metadata-pills">
                  {[book.status, book.asura_type, book.asura_author && `Author: ${book.asura_author}`, book.asura_artist && `Artist: ${book.asura_artist}`]
                    .filter(Boolean)
                    .map((item) => <span key={String(item)}>{item}</span>)}
                </div>
                {book.latest_read && (
                  <a className="btn-primary latest-read-btn" href={book.latest_read.komga_url} target="_blank" rel="noreferrer">
                    <Play size={14} />
                    Jump to {book.latest_read.label}
                    {book.latest_read.page > 0 && <span>page {book.latest_read.page}</span>}
                  </a>
                )}
              </div>
              <div className="browse-modal-stats">
                <StatCard label="Local" value={`${book.local_chapter_count}`} />
                <StatCard label="Asura" value={`${book.remote_chapter_count}`} />
                <StatCard label="Missing" value={`${book.missing_count}`} />
                <StatCard label="Rating" value={book.asura_rating != null ? `${book.asura_rating}` : "n/a"} />
              </div>
            </div>

            <div className="metadata-panel">
              <span className="field-label">Metadata</span>
              <div className="metadata-grid">
                <GenreMeta genres={genreNames(book)} />
                <Meta label="Asura" value={book.url} href={book.url} />
                <Meta label="Komga series" value={komgaSeriesUrl || "sync metadata to link"} href={komgaSeriesUrl || undefined} />
                <Meta label="Last scanned" value={book.last_scanned_at ? new Date(book.last_scanned_at).toLocaleString() : "never"} />
                <Meta label="Metadata synced" value={book.metadata_synced_at ? new Date(book.metadata_synced_at).toLocaleString() : "never"} />
                <Meta label="Local folder" value={book.local_folder || "n/a"} />
              </div>
            </div>

            <div className="chapter-panel">
              <div className="chapter-head">
                <span className="field-label">Chapters</span>
                <div className="results-nav">
                  <button className="btn-ghost btn-sm" disabled={chapterPage === 0} onClick={() => setChapterPage(Math.max(0, chapterPage - 1))}>Previous</button>
                  <span className="muted">{chapterPage + 1} / {chapterPages}</span>
                  <button className="btn-ghost btn-sm" disabled={chapterPage + 1 >= chapterPages} onClick={() => setChapterPage(chapterPage + 1)}>Next</button>
                </div>
              </div>
              <form className="chapter-read-tools" onSubmit={markReadThrough}>
                <label>
                  <span>Read through</span>
                  <input
                    type="number"
                    step="0.1"
                    value={readThroughChapter}
                    onChange={(event) => setReadThroughChapter(event.target.value)}
                    placeholder="Chapter"
                    disabled={!book.komga_series_id || readThroughBusy}
                  />
                </label>
                <button className="btn-primary btn-sm" disabled={!book.komga_series_id || readThroughBusy}>
                  <BookCheck size={13} /> Mark read
                </button>
                {readThroughStatus && <span className="muted">{readThroughStatus}</span>}
              </form>
              <div className="chapter-list">
                {pageChapters.map((chapter) => (
                  <a key={chapter.id} className="chapter-link" href={chapter.komga_url || komgaSeriesUrl || book.url} target="_blank" rel="noreferrer">
                    <span>{chapter.label}</span>
                    <small>{chapter.is_downloaded ? "downloaded by app" : book.local_chapters.includes(chapter.chapter_key) ? "on disk" : "remote"}</small>
                  </a>
                ))}
                {pageChapters.length === 0 && <p className="empty">No chapter list is stored yet.</p>}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value, href }: { label: string; value: string; href?: string }) {
  return (
    <div className="metadata-row">
      <span>{label}</span>
      {href ? <a href={href} target="_blank" rel="noreferrer">{value}</a> : <strong>{value}</strong>}
    </div>
  );
}

function GenreMeta({ genres }: { genres: string[] }) {
  return (
    <div className="metadata-row metadata-row-wide">
      <span>Genres</span>
      {genres.length > 0 ? (
        <div className="genre-chip-wrap">
          {genres.map((genre) => <strong key={genre}>{genre}</strong>)}
        </div>
      ) : (
        <strong>n/a</strong>
      )}
    </div>
  );
}

function genreNames(book: Book | BookDetail): string[] {
  return (book.asura_genres || [])
    .map((genre) => (typeof genre === "string" ? genre : genre.name || genre.slug || ""))
    .filter(Boolean);
}
