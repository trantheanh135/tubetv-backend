import asyncio
import contextlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from cachetools import TTLCache
from fastapi import FastAPI, HTTPException, Query

from . import youtube

CATEGORIES = [
    {"id": "trending", "title": "Thịnh hành", "query": "thịnh hành việt nam hôm nay"},
    {"id": "music", "title": "Âm nhạc", "query": "nhạc việt hot nhất"},
    {"id": "comedy", "title": "Hài", "query": "hài kịch việt nam"},
    {"id": "news", "title": "Tin tức", "query": "tin tức thời sự hôm nay"},
    {"id": "kids", "title": "Thiếu nhi", "query": "hoạt hình thiếu nhi tiếng việt"},
    {"id": "cooking", "title": "Nấu ăn", "query": "nấu ăn món ngon mỗi ngày"},
    {"id": "tech", "title": "Công nghệ", "query": "review công nghệ mới"},
]

SEARCH_TTL = int(os.getenv("SEARCH_TTL", "900"))
# Stream URLs from YouTube live ~6h; keep ours well under that.
RESOLVE_TTL = int(os.getenv("RESOLVE_TTL", "1500"))

log = logging.getLogger("tubetv")


# Fixed workers so each keeps its own warmed-up yt-dlp instance (see youtube._resolver).
_WORKERS = int(os.getenv("MAX_CONCURRENCY", "3"))
_pool = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="yt")


def _warm_up() -> None:
    # The first resolve on each instance spends ~40s initialising yt-dlp's JS challenge solver; do it now.
    def one(_: int) -> None:
        try:
            youtube.resolve("9bZkp7q19f0")
            log.info("warm-up resolve done")
        except Exception as e:
            log.warning("warm-up resolve failed: %s", e)

    list(_pool.map(one, range(_WORKERS)))


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("WARM_UP", "1") == "1":
        threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="tubetv-backend", lifespan=lifespan)
_search_cache: TTLCache = TTLCache(maxsize=256, ttl=SEARCH_TTL)
_resolve_cache: TTLCache = TTLCache(maxsize=256, ttl=RESOLVE_TTL)
_gate = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENCY", "3")))


async def _run(fn, *args) -> Any:
    async with _gate:
        return await asyncio.get_running_loop().run_in_executor(_pool, fn, *args)


async def _search(query: str, count: int) -> list[dict[str, Any]]:
    key = (query.strip().lower(), count)
    if key in _search_cache:
        return _search_cache[key]
    try:
        items = await _run(youtube.search, query, count)
    except Exception as e:  # yt-dlp raises many types; all mean "upstream failed"
        raise HTTPException(502, f"search failed: {e}") from e
    _search_cache[key] = items
    return items


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/categories")
def categories() -> list[dict[str, str]]:
    return [{"id": c["id"], "title": c["title"]} for c in CATEGORIES]


@app.get("/api/feed/{category_id}")
async def feed(category_id: str, limit: int = Query(24, ge=1, le=50)) -> list[dict[str, Any]]:
    cat = next((c for c in CATEGORIES if c["id"] == category_id), None)
    if cat is None:
        raise HTTPException(404, "unknown category")
    return (await _search(cat["query"], limit))[:limit]


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1, max_length=120),
                 page: int = Query(1, ge=1, le=5), size: int = 20) -> list[dict[str, Any]]:
    # yt-dlp has no cursor for flat search: fetch page*size and slice.
    size = max(1, min(size, 30))
    items = await _search(q, page * size)
    return items[(page - 1) * size: page * size]


@app.get("/api/channel/{channel_id}")
async def channel(channel_id: str, limit: int = Query(24, ge=1, le=50)) -> list[dict[str, Any]]:
    key = ("channel", channel_id, limit)
    if key in _search_cache:
        return _search_cache[key]
    try:
        items = await _run(youtube.channel_videos, channel_id, limit)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"channel failed: {e}") from e
    _search_cache[key] = items
    return items


@app.get("/api/channels/search")
async def channel_search(q: str = Query(..., min_length=1, max_length=120)) -> list[dict[str, str]]:
    # Channels behind the first 30 video hits; flat search has no channel-only mode.
    return youtube.channels_from(await _search(q, 30))


@app.get("/api/video/{video_id}")
async def video(video_id: str) -> dict[str, Any]:
    cached = _resolve_cache.get(video_id)
    if cached:
        return cached
    try:
        data = await _run(youtube.resolve, video_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"resolve failed: {e}") from e
    data["resolvedAt"] = int(time.time())
    _resolve_cache[video_id] = data
    return data
