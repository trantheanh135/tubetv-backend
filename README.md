# tubetv-backend

FastAPI + yt-dlp service behind the TubeTV Android TV app. It searches YouTube, lists category
feeds, and resolves a video id to direct H.264/AAC stream URLs that the TV plays and merges itself.

| Endpoint | Purpose |
|---|---|
| `GET /api/categories` | Home-screen rows |
| `GET /api/feed/{id}?limit=` | Videos for a category |
| `GET /api/search?q=&page=&size=` | Search |
| `GET /api/video/{id}` | Title, description and stream URLs (`video`+`audio`, `muxed`, `hls`) |
| `GET /healthz` | Probe |

Stream URLs are tied to the requesting IP and expire in about 6 hours, so the TV must be on the same
network (same public IP) as this server. Results are cached in memory (search 15 min, resolve 25 min).

Deploy: GitHub Actions builds the image nightly and on push, pins it in `k8s/tubetv.yaml`, ArgoCD syncs
it to namespace `tubetv`, NodePort `30891`.

Personal use only: YouTube's terms do not allow this kind of access for redistribution.
