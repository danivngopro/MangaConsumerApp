from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .utils import chapter_key, fix_mojibake, normalize_title, slugify


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)


@dataclass(frozen=True)
class AsuraSeries:
    slug: str
    title: str
    url: str
    cover_url: str | None
    status: str | None
    remote_chapter_count: int
    type: str | None = None
    author: str | None = None
    artist: str | None = None
    genres: list | None = None
    rating: float | None = None
    description: str | None = None
    last_chapter_at: str | None = None


@dataclass(frozen=True)
class AsuraChapter:
    number: str
    label: str
    url: str


class AsuraClient:
    def __init__(self, base_url: str, request_delay_seconds: float = 1.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_base_url = "https://api.asurascans.com/api"
        self.request_delay_seconds = request_delay_seconds
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/browse",
        })

    def _get(self, path_or_url: str) -> str:
        url = path_or_url if path_or_url.startswith("http") else urljoin(self.base_url, path_or_url)
        response = self.session.get(url, timeout=45)
        response.raise_for_status()
        if self.request_delay_seconds:
            time.sleep(self.request_delay_seconds)
        return response.text

    def _api_get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        response = self.session.get(f"{self.api_base_url}{path}", params=params or {}, timeout=45)
        response.raise_for_status()
        if self.request_delay_seconds:
            time.sleep(self.request_delay_seconds)
        return response.json()

    def browse_filters(self) -> dict:
        genres_response = self._api_get("/genres")
        creators_response = self._api_get("/creators")
        creators = creators_response.get("data") or creators_response
        return {
            "genres": genres_response.get("data") or genres_response,
            "authors": creators.get("authors", []),
            "artists": creators.get("artists", []),
            "statuses": ["all", "ongoing", "completed", "hiatus", "dropped", "axed"],
            "types": ["all", "manhwa", "manhua", "manga"],
            "sorts": ["latest", "popular", "rating", "title", "chapters", "created_at"],
        }

    def search_series(
        self,
        search: str = "",
        genres: str = "",
        author: str = "",
        artist: str = "",
        status: str = "all",
        series_type: str = "all",
        sort: str = "latest",
        order: str = "desc",
        min_chapters: int = 0,
        max_chapters: int = 0,
        limit: int = 24,
        offset: int = 0,
    ) -> dict:
        params: dict[str, Any] = {
            "sort": sort or "latest",
            "order": order or "desc",
            "limit": max(1, min(100, int(limit))),
            "offset": max(0, int(offset)),
        }
        if search:
            params["search"] = search
        if genres:
            params["genres"] = genres
        if author:
            params["author"] = author
        if artist:
            params["artist"] = artist
        if status and status != "all":
            params["status"] = status
        if series_type and series_type != "all":
            params["type"] = series_type
        if min_chapters > 0:
            params["min_chapters"] = min_chapters
        if max_chapters > 0:
            params["max_chapters"] = max_chapters

        payload = self._api_get("/series", params)
        items = payload.get("data") or []
        if max_chapters > 0:
            items = [item for item in items if int(item.get("chapter_count") or 0) <= max_chapters]
        normalized_items = []
        for item in items:
            title = fix_mojibake(str(item.get("title") or "Untitled"))
            public_url = item.get("public_url") or f"/comics/{item.get('slug', '')}"
            normalized_items.append({
                "id": item.get("id"),
                "slug": item.get("slug"),
                "title": title,
                "url": urljoin(self.base_url, public_url),
                "cover_url": item.get("cover"),
                "status": item.get("status"),
                "type": item.get("type"),
                "author": item.get("author"),
                "artist": item.get("artist"),
                "genres": item.get("genres") or [],
                "chapter_count": int(item.get("chapter_count") or 0),
                "rating": item.get("rating"),
                "last_chapter_at": item.get("last_chapter_at"),
                "popularity_rank": item.get("popularity_rank"),
            })
        meta = payload.get("meta") or {}
        return {
            "items": normalized_items,
            "total": int(meta.get("total") or len(normalized_items)),
            "limit": params["limit"],
            "offset": params["offset"],
        }

    def crawl_catalog(
        self,
        max_pages: int = 200,
        limit: int | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[AsuraSeries]:
        series: dict[str, AsuraSeries] = {}
        page = 1

        while page <= max_pages:
            if should_stop and should_stop():
                break
            path = "/browse" if page == 1 else f"/browse?page={page}"
            text = self._get(path)
            if should_stop and should_stop():
                break
            page_items = self.parse_browse_page(text)
            for item in page_items:
                if should_stop and should_stop():
                    break
                series[item.slug] = item
                if limit and len(series) >= limit:
                    return list(series.values())[:limit]

            if not page_items or not self._has_next_page(text, page):
                break
            page += 1

        return list(series.values())

    def parse_browse_page(self, text: str) -> list[AsuraSeries]:
        soup = BeautifulSoup(text, "html.parser")
        items: list[AsuraSeries] = []

        for card in soup.select(".series-card"):
            link = card.select_one('a[href^="/comics/"]')
            title_node = card.select_one("h3")
            if not link or not title_node:
                continue
            title = fix_mojibake(title_node.get_text(" ", strip=True))
            url = urljoin(self.base_url, link.get("href", ""))
            slug = self._slug_from_url(url) or slugify(title)
            cover = card.select_one("img")
            chapter_text = card.get_text(" ", strip=True)
            count_match = re.search(r"(\d+)\s+Chapters", chapter_text, re.IGNORECASE)
            status_match = re.search(r"\b(ongoing|completed|hiatus|dropped)\b", chapter_text, re.IGNORECASE)
            items.append(
                AsuraSeries(
                    slug=slug,
                    title=title,
                    url=url,
                    cover_url=cover.get("src") if cover else None,
                    status=status_match.group(1).lower() if status_match else None,
                    remote_chapter_count=int(count_match.group(1)) if count_match else 0,
                )
            )

        if items:
            return items

        # Fallback for Astro serialized payloads and homepage/latest blocks.
        seen = set()
        for match in re.finditer(r"/comics/([a-z0-9-]+(?:-46f09241)?)", text):
            slug = match.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            title = self._title_from_slug(slug)
            items.append(
                AsuraSeries(
                    slug=slug,
                    title=title,
                    url=urljoin(self.base_url, f"/comics/{slug}"),
                    cover_url=None,
                    status=None,
                    remote_chapter_count=0,
                )
            )
        return items

    def fetch_series(self, series_url: str) -> tuple[AsuraSeries, list[AsuraChapter]]:
        text = self._get(series_url)
        soup = BeautifulSoup(text, "html.parser")
        canonical = soup.select_one('link[rel="canonical"]')
        url = canonical.get("href") if canonical else series_url
        title_node = soup.select_one('meta[property="og:title"]')
        title = (title_node.get("content", "").replace("| Asura Scans", "").strip() if title_node else "")
        if not title:
            title = soup.select_one("h1").get_text(" ", strip=True) if soup.select_one("h1") else self._title_from_slug(url)

        cover_node = soup.select_one('meta[property="og:image"]')
        description_node = (
            soup.select_one('meta[property="og:description"]')
            or soup.select_one('meta[name="description"]')
        )
        description = fix_mojibake(description_node.get("content", "").strip()) if description_node else None
        episode_match = re.search(r'"numberOfEpisodes"\s*:\s*(\d+)', text)
        status_match = re.search(r"\b(ongoing|completed|hiatus|dropped)\b", soup.get_text(" ", strip=True), re.IGNORECASE)
        series_type = self._detail_type(soup)
        author = self._detail_creator(soup, "author")
        artist = self._detail_creator(soup, "artist")
        genres = self._detail_genres(soup)
        series = AsuraSeries(
            slug=self._slug_from_url(url) or slugify(title),
            title=fix_mojibake(title),
            url=url,
            cover_url=cover_node.get("content") if cover_node else None,
            status=status_match.group(1).lower() if status_match else None,
            remote_chapter_count=int(episode_match.group(1)) if episode_match else 0,
            type=series_type,
            author=author,
            artist=artist,
            genres=genres,
            description=description,
        )
        chapters = self.parse_chapters(text, url)
        if chapters and not series.remote_chapter_count:
            series = AsuraSeries(
                slug=series.slug,
                title=series.title,
                url=series.url,
                cover_url=series.cover_url,
                status=series.status,
                remote_chapter_count=len(chapters),
                type=series.type,
                author=series.author,
                artist=series.artist,
                genres=series.genres,
                rating=series.rating,
                description=series.description,
                last_chapter_at=series.last_chapter_at,
            )
        return series, chapters

    def _detail_creator(self, soup: BeautifulSoup, key: str) -> str | None:
        node = soup.select_one(f'a[href*="{key}="]')
        if not node:
            return None
        value = fix_mojibake(node.get_text(" ", strip=True))
        return value or None

    def _detail_genres(self, soup: BeautifulSoup) -> list[dict]:
        genres: list[dict] = []
        seen: set[str] = set()
        for node in soup.select('a[href*="genres="]'):
            href = node.get("href", "")
            slug_match = re.search(r"genres=([^&]+)", href)
            slug = slug_match.group(1).strip().lower() if slug_match else slugify(node.get_text(" ", strip=True))
            name = fix_mojibake(node.get_text(" ", strip=True))
            if not slug or slug in seen:
                continue
            seen.add(slug)
            genres.append({"name": name or self._title_from_slug(slug), "slug": slug})
        return genres

    def _detail_type(self, soup: BeautifulSoup) -> str | None:
        text = soup.get_text(" ", strip=True)
        match = re.search(r"\b(manhwa|manhua|manga)\b", text, re.IGNORECASE)
        return match.group(1).lower() if match else None

    def parse_chapters(self, text: str, series_url: str) -> list[AsuraChapter]:
        found: dict[str, AsuraChapter] = {}
        soup = BeautifulSoup(text, "html.parser")

        for link in soup.select('a[href*="/chapter/"]'):
            href = link.get("href", "")
            number = self._chapter_number_from_url(href)
            key = chapter_key(number)
            if not key:
                continue
            label = link.get_text(" ", strip=True) or f"Chapter {key}"
            if not re.search(r"\bchapter\s*\d", label, re.IGNORECASE):
                continue
            found[key] = AsuraChapter(number=key, label=fix_mojibake(label), url=urljoin(self.base_url, href))

        if not found:
            for match in re.finditer(r'(/comics/[^"\s<>]+/chapter/(\d+(?:\.\d+)?))', text):
                key = chapter_key(match.group(2))
                if key and key not in found:
                    found[key] = AsuraChapter(
                        number=key,
                        label=f"Chapter {key}",
                        url=urljoin(self.base_url, html.unescape(match.group(1))),
                    )

        if not found:
            count_match = re.search(r'"numberOfEpisodes"\s*:\s*(\d+)', text)
            if count_match:
                count = int(count_match.group(1))
                base = series_url.rstrip("/")
                for number in range(1, count + 1):
                    key = str(number)
                    found[key] = AsuraChapter(
                        number=key,
                        label=f"Chapter {key}",
                        url=f"{base}/chapter/{key}",
                    )

        return sorted(found.values(), key=lambda chapter: float(chapter.number))

    def find_series(self, query: str) -> AsuraSeries | None:
        if query.startswith("http"):
            series, _ = self.fetch_series(query)
            return series

        wanted = normalize_title(query)
        for series in self.crawl_catalog():
            normalized = normalize_title(series.title)
            if normalized == wanted or wanted in normalized or normalized in wanted:
                return series
        return None

    def _has_next_page(self, text: str, page: int) -> bool:
        return f'/browse?page={page + 1}' in text or f"/browse?page={page + 1}" in text

    def _slug_from_url(self, value: str) -> str:
        path = urlparse(value).path.strip("/")
        if path.startswith("comics/"):
            return path.split("/")[1]
        return ""

    def _chapter_number_from_url(self, value: str) -> str:
        match = re.search(r"/chapter/(\d+(?:\.\d+)?)", value)
        return match.group(1) if match else ""

    def _title_from_slug(self, value: str) -> str:
        slug = self._slug_from_url(value) or value
        slug = re.sub(r"-46f09241$", "", slug)
        return " ".join(part.capitalize() for part in slug.split("-"))
