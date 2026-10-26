import os

os.environ["WARM_UP"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import main, youtube

client = TestClient(main.app)

FORMATS = [
    {"format_id": "18", "protocol": "https", "url": "https://x/18?expire=1900000000", "vcodec": "avc1.42", "acodec": "mp4a.40", "height": 360, "tbr": 500},
    {"format_id": "137", "protocol": "https", "url": "https://x/137?expire=1900000000", "vcodec": "avc1.64", "acodec": "none", "height": 1080, "tbr": 4000},
    {"format_id": "136", "protocol": "https", "url": "https://x/136", "vcodec": "avc1.64", "acodec": "none", "height": 720, "tbr": 2000},
    {"format_id": "299", "protocol": "https", "url": "https://x/299", "vcodec": "avc1.64", "acodec": "none", "height": 2160, "tbr": 9000},
    {"format_id": "313", "protocol": "https", "url": "https://x/313", "vcodec": "vp9", "acodec": "none", "height": 1080, "tbr": 9000},
    {"format_id": "140", "protocol": "https", "url": "https://x/140", "vcodec": "none", "acodec": "mp4a.40", "abr": 128},
    {"format_id": "251", "protocol": "https", "url": "https://x/251", "vcodec": "none", "acodec": "opus", "abr": 160},
]


def test_pick_streams_prefers_h264_1080_and_aac():
    s = youtube.pick_streams(FORMATS)
    assert s["video"]["url"] == "https://x/137?expire=1900000000"
    assert s["video"]["height"] == 1080
    assert s["audio"]["url"] == "https://x/140"
    assert s["muxed"]["url"].startswith("https://x/18")
    assert [v["height"] for v in s["videos"]] == [720, 1080]


def test_pick_streams_without_audio_only_muxed():
    s = youtube.pick_streams([f for f in FORMATS if f["format_id"] in ("18", "137")])
    assert "video" not in s and "muxed" in s


def test_video_endpoint_resolves_and_caches(monkeypatch):
    calls = []

    def fake(video_id):
        calls.append(video_id)
        return {"id": video_id, "title": "t", "streams": {}, "expiresAt": 1}

    monkeypatch.setattr(youtube, "resolve", fake)
    main._resolve_cache.clear()
    assert client.get("/api/video/abcdefghijk").json()["title"] == "t"
    client.get("/api/video/abcdefghijk")
    assert calls == ["abcdefghijk"]


def test_video_bad_id_is_400():
    main._resolve_cache.clear()
    assert client.get("/api/video/short").status_code == 400


def test_search_paginates_from_one_fetch(monkeypatch):
    monkeypatch.setattr(youtube, "search", lambda q, n: [{"id": f"{i:011d}"} for i in range(n)])
    main._search_cache.clear()
    p2 = client.get("/api/search", params={"q": "x", "page": 2, "size": 5}).json()
    assert [i["id"] for i in p2] == [f"{i:011d}" for i in range(5, 10)]


def test_feed_unknown_category_404():
    assert client.get("/api/feed/nope").status_code == 404


def test_categories_listed():
    assert client.get("/api/categories").json()[0]["id"] == "trending"


def test_channel_search_dedupes_channels(monkeypatch):
    cards = [
        {"id": "a" * 11, "channel": "A", "channelId": "UC1", "thumb": "t1"},
        {"id": "b" * 11, "channel": "A", "channelId": "UC1", "thumb": "t2"},
        {"id": "c" * 11, "channel": "B", "channelId": "UC2", "thumb": "t3"},
        {"id": "d" * 11, "channel": "C", "channelId": "", "thumb": "t4"},
    ]
    monkeypatch.setattr(youtube, "search", lambda q, n: cards)
    main._search_cache.clear()
    res = client.get("/api/channels/search", params={"q": "kids"}).json()
    assert [c["id"] for c in res] == ["UC1", "UC2"]
    assert res[0]["thumb"] == "t1"


def test_channel_bad_id_is_400():
    assert client.get("/api/channel/nope").status_code == 400


def test_channel_feed_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(youtube, "channel_videos", lambda cid, n: calls.append(cid) or [{"id": "x" * 11}])
    main._search_cache.clear()
    cid = "UC" + "a" * 22
    assert client.get(f"/api/channel/{cid}").json() == [{"id": "x" * 11}]
    client.get(f"/api/channel/{cid}")
    assert calls == [cid]
