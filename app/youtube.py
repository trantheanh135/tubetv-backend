"""Thin yt-dlp wrapper: flat search results and stream resolution."""
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp

MAX_HEIGHT = 1080


def _opts(**extra: Any) -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "extractor_retries": 2,
        **extra,
    }


def _thumb(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _card(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": e["id"],
        "title": e.get("title") or "",
        "channel": e.get("channel") or e.get("uploader") or "",
        "duration": int(e["duration"]) if e.get("duration") else None,
        "views": e.get("view_count"),
        "thumb": _thumb(e["id"]),
        "live": e.get("live_status") == "is_live",
    }


def search(query: str, count: int) -> list[dict[str, Any]]:
    with yt_dlp.YoutubeDL(_opts(extract_flat="in_playlist")) as ydl:
        info = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
    out = []
    for e in info.get("entries") or []:
        if not e or not e.get("id") or len(e["id"]) != 11:
            continue  # skips channels/playlists that sneak into search
        out.append(_card(e))
    return out


def _expiry(url: str) -> int | None:
    try:
        return int(parse_qs(urlparse(url).query)["expire"][0])
    except (KeyError, ValueError, IndexError):
        return None


def pick_streams(formats: list[dict[str, Any]], max_height: int = MAX_HEIGHT) -> dict[str, Any]:
    """Choose a video+audio pair the TV can merge, plus a muxed fallback and a live HLS URL.

    H.264/AAC only: the box decodes those in hardware; VP9/AV1 would fall back to software.
    """

    def https(f: dict[str, Any]) -> bool:
        return f.get("protocol") in ("https", "http") and bool(f.get("url"))

    def has(f: dict[str, Any], key: str) -> bool:
        return (f.get(key) or "none") != "none"

    videos = [
        f for f in formats
        if https(f) and (f.get("vcodec") or "").startswith("avc1") and not has(f, "acodec")
        and (f.get("height") or 0) <= max_height
    ]
    audios = [
        f for f in formats
        if https(f) and not has(f, "vcodec") and (f.get("acodec") or "").startswith("mp4a")
    ]
    muxed = [
        f for f in formats
        if https(f) and has(f, "vcodec") and has(f, "acodec") and (f.get("height") or 0) <= max_height
    ]
    hls = [
        f for f in formats
        if f.get("protocol") in ("m3u8", "m3u8_native") and has(f, "vcodec") and has(f, "acodec")
        and (f.get("height") or 0) <= max_height
    ]

    def best(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
        return max(items, key=lambda f: (f.get("height") or 0, f.get(key) or 0), default=None)

    def entry(f: dict[str, Any]) -> dict[str, Any]:
        return {"url": f["url"], "height": f.get("height"), "headers": f.get("http_headers") or {}}

    v, a, m, h = best(videos, "tbr"), best(audios, "abr"), best(muxed, "tbr"), best(hls, "tbr")
    result: dict[str, Any] = {}
    if v and a:
        result["video"] = entry(v)
        result["audio"] = entry(a)
        # One variant per height (best bitrate), ascending, so the TV can pick a quality it decodes smoothly.
        per_height: dict[int, dict[str, Any]] = {}
        for f in videos:
            hgt = f.get("height") or 0
            if hgt not in per_height or (f.get("tbr") or 0) > (per_height[hgt].get("tbr") or 0):
                per_height[hgt] = f
        result["videos"] = [entry(per_height[k]) for k in sorted(per_height)]
    if m:
        result["muxed"] = entry(m)
    if h:
        result["hls"] = entry(h)
    return result


def resolve(video_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("bad video id")
    with yt_dlp.YoutubeDL(_opts()) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    streams = pick_streams(info.get("formats") or [])
    if not streams:
        raise LookupError("no playable stream")
    first = (streams.get("video") or streams.get("muxed") or streams.get("hls"))["url"]
    return {
        "id": video_id,
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "description": (info.get("description") or "")[:1500],
        "duration": int(info["duration"]) if info.get("duration") else None,
        "live": bool(info.get("is_live")),
        "thumb": _thumb(video_id),
        "streams": streams,
        "expiresAt": _expiry(first),
    }
