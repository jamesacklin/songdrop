# Songdrop

Song-first requests for a self-hosted music library. Shazam a track at a coffee
shop, open the app, search, tap **Add to Library** — and the next time you're
home it's in Plex, properly tagged, with album art, in the playlist you asked for.

The flow (as described in [Joe Karlsson's post](https://www.joekarlsson.com/blog/self-hosted-music-still-sucks-in-2026/)):

```
iOS app ──▶ Songdrop server ──▶ slskd (Soulseek) ──▶ tag (mutagen) ──▶ Plex library
   search      request queue        acquisition          metadata +        partial scan +
   (Deezer)                                              album art         playlist add
                                                                              │
                                                                              ▼
                                                                        ntfy push: "ready"
```

- **Search** uses the Deezer public API for clean metadata (title/artist/album/art) — no key needed.
- **Acquisition** goes through slskd's REST API: search Soulseek, score the results
  (FLAC > 320kbps MP3, filename match, free upload slots, upload speed, queue length),
  download the best candidate, and fall back to the next candidate on failure.
- **YouTube fallback** (yt-dlp): when Soulseek has nothing, the best-matching YouTube
  audio is grabbed instead (~128kbps AAC m4a — last resort, not a FLAC replacement).
  Videos are scored by title match, "Artist - Topic" channels, and closeness to the
  catalog duration; live cuts/covers/remixes are penalized. Disable with
  `YTDLP_ENABLED=false`. A request can also carry a `youtube_url` to acquire from an
  exact video, skipping Soulseek — the app's manual-request sheet has a field for it.
- **Tagging** embeds title, artist, album, album artist, track/disc numbers, year, and
  cover art (FLAC, MP3, M4A, OGG) using metadata from Deezer.
- **Import** moves the file into `{library}/{Album Artist}/{Album}/{NN - Title}.ext`,
  triggers a partial Plex scan of just that folder, waits for the track to appear,
  and adds it to the requested playlist (creating it if needed).
- **Notifications** are optional via [ntfy](https://ntfy.sh) — you get a push when the
  track is ready (or when a request fails).

Requests survive restarts (SQLite queue); anything mid-flight when the server dies is
re-queued on startup.

## Server setup

The server is published as a multi-arch (amd64 + arm64) image on Docker Hub:
[`jamesacklin/songdrop`](https://hub.docker.com/r/jamesacklin/songdrop).

```bash
docker run -d --name songdrop -p 8585:8585 \
  -v songdrop-data:/data \
  -v /srv/plex/music:/music \
  -v /srv/slskd/downloads:/downloads \
  -e SLSKD_URL=http://your-slskd:5030 \
  -e SLSKD_USERNAME=you -e SLSKD_PASSWORD=secret \
  -e PLEX_URL=http://your-plex:32400 -e PLEX_TOKEN=xxxx \
  jamesacklin/songdrop:latest

docker logs songdrop 2>&1 | grep -A2 "access key"   # <- your access key
```

slskd and Plex can also be configured from the app's **Settings** later instead of
env vars — but the **volume mounts below are not configurable at runtime**, so get
them right at `docker run` / compose time.

### Volumes — get these right

| Container path | What it holds | Must be mounted to… |
| --- | --- | --- |
| `/data` | SQLite request queue + the auto-generated access key | any persistent volume (named volume or host dir) so it survives restarts |
| `/music` | where finished tracks are filed (`Artist/Album/NN - Title.ext`) | **the exact folder your Plex music library scans** |
| `/downloads` | where slskd drops completed files, so the server can find them | **the same folder your slskd writes completed downloads to** |

**The #1 gotcha (files download but never show up in Plex):** if `/music` isn't the
same underlying folder your Plex music library points at, tracks are acquired and filed
successfully but land somewhere Plex can't see — and if you didn't mount `/music` at
all, they sit in the container's ephemeral filesystem and vanish on the next
`docker rm`. Mount `/music` to your real Plex music folder.

**Path mapping (`PLEX_LIBRARY_DIR`):** Songdrop and Plex are usually separate
containers that mount the *same host folder at different container paths*. Songdrop
writes to `/music`; if your Plex has that library added as, say, `/media`, set
`-e PLEX_LIBRARY_DIR=/media` so the scan targets the path Plex actually knows. Example:

```
host: /srv/plex/music
  ├── mounted into Songdrop as /music   (MUSIC_LIBRARY_DIR, default)
  └── mounted into Plex           as /media  → set PLEX_LIBRARY_DIR=/media
```

The app's **Settings → Storage** shows the effective `/downloads`, `/music`, and
"Plex reads" paths so you can confirm the mapping without shelling into the container.
After a request finishes, the status is honest about it: `ready to play` only if Plex
actually indexed the track, otherwise it tells you the file is filed on disk but Plex
hasn't picked it up (check this mapping).

### Access key

`SONGDROP_API_KEY` is **optional** — leave it unset and the server generates a key on
first boot, persists it in `/data`, and prints it to the logs (`docker logs`). Set the
env var to pin your own. Either way, enter it as the **Access key** in the app/PWA.

### Other notes

- **slskd**: open `http://your-server:5030`, log in, add your Soulseek credentials. Give
  Songdrop access with either an API key (Options → Web → Authentication → API keys,
  set `SLSKD_API_KEY`) or `SLSKD_USERNAME`/`SLSKD_PASSWORD`. Songdrop must be able to
  read slskd's completed-downloads folder at `SLSKD_DOWNLOADS_DIR` (`/downloads`) — mount
  the same host folder into both containers.
- **Plex token**: any signed-in Plex Web session → open an item → Get Info → View XML →
  copy `X-Plex-Token` from the URL.
- **YouTube fallback**: on by default; disable with `YTDLP_ENABLED=false` or the toggle in
  Settings → Sources.
- **Lidarr coexistence**: Songdrop writes normal `Artist/Album/NN - Title.ext` files,
  so it sits happily next to a Lidarr-managed library.

### From source (docker compose)

The bundled compose runs slskd + Songdrop together and wires the volumes for you:

```bash
cp .env.example .env
# set MUSIC_LIBRARY_PATH to the HOST path of your Plex music folder;
# set PLEX_URL / PLEX_TOKEN and slskd creds. SONGDROP_API_KEY is optional.
docker compose up -d --build
docker compose logs songdrop | grep -A2 "access key"
```

Or without Docker:

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SLSKD_URL=... SLSKD_USERNAME=... SLSKD_PASSWORD=... \
MUSIC_LIBRARY_DIR=/path/to/plex/music SLSKD_DOWNLOADS_DIR=/path/to/downloads \
PLEX_URL=... PLEX_TOKEN=... \
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8585
```

## iOS app

The app is plain SwiftUI (iOS 17+), built with [XcodeGen](https://github.com/yonaskolb/XcodeGen):

```bash
brew install xcodegen
cd ios
xcodegen generate
open Songdrop.xcodeproj
```

In Xcode: select the Songdrop target → Signing & Capabilities → pick your team, then
build to your phone. In the app's **Settings** tab, enter your server URL and the
`SONGDROP_API_KEY`, and hit **Test Connection**.

**Reaching the server away from home**: the whole point is requesting songs from a
coffee shop, so put the server behind Tailscale/WireGuard (recommended) or a reverse
proxy with TLS + the API key. The project's Info.plist allows plain-HTTP for
LAN/VPN use; remove `NSAllowsArbitraryLoads` from `project.yml` if you serve HTTPS.

## Web app (PWA)

The server also hosts a progressive web app that mirrors the iOS front-end — the
same Search / Requests / Settings tabs, flows, and iOS look. It's served at the
server root (`/`) from `server/app/static/` (no build step), talks to the same
API same-origin, and is installable to the home screen (`manifest.webmanifest`
+ a service worker that caches the shell but never the API). On first load it
asks for the server address (prefilled to the current origin) and access key,
stored on-device. Nothing else to run — visiting the server in a browser is the
whole install.

## API

All endpoints (except `/api/health`) require the `X-API-Key` header.

| Endpoint | Description |
| --- | --- |
| `GET /api/search?q=` | Track metadata search (Deezer + iTunes, merged and deduped) |
| `GET /api/album?artist=&album=` | Full album tracklist — MusicBrainz first (includes tracks streaming omits), Deezer fallback |
| `GET /api/status` | Downstream health: slskd reachability + Soulseek connection state, Plex reachability |
| `GET/PUT /api/config` | slskd/Plex connection settings — editable from the app, persisted in the DB, applied without restart (env vars remain the defaults) |
| `POST /api/requests` | `{artist, title, album?, deezer_id?, playlist?}` — queue an acquisition |
| `POST /api/requests/bulk` | `{requests: [...]}` (≤100) — queue a whole album; skips tracks with live requests or already in the Plex library |
| `GET /api/requests` | Downloads list with per-request status/detail/error |
| `POST /api/requests/{id}/retry` | Search again now (failed or waiting requests) |
| `DELETE /api/requests/{id}` | Remove a finished/failed/waiting request |
| `POST /api/import` | `{path, artist, title, album?, deezer_id?, playlist?}` — tag a file already on disk and move it into the Plex library |
| `GET /api/playlists` | Plex audio playlists (for the picker) |

`POST /api/import` is the "moving files on disk into my Plex library" path — point it
at any audio file on the server (an old download, something you ripped, a file another
tool grabbed) and it goes through the same tag → move → scan → playlist pipeline.

Example:

```bash
curl -X POST http://server:8585/api/import \
  -H "X-API-Key: $SONGDROP_API_KEY" -H "Content-Type: application/json" \
  -d '{"path": "/downloads/some album/07 - Midnight City.flac",
       "artist": "M83", "title": "Midnight City", "playlist": "Coffee Shop Finds"}'
```

## Request lifecycle

`queued → searching → downloading → tagging → importing → done` (or `failed`, with the
reason shown in the app; failed requests can be retried with a swipe).

If a search finds nothing (or every peer flakes out), the request goes to `waiting`
and is retried automatically every 10 minutes (`RETRY_INTERVAL`, seconds) — the app's
Downloads tab shows a live countdown to the next search. Retries continue until the
song is found or you delete the request (`MAX_SEARCH_RETRIES` caps them if you
prefer; `0` = unlimited). Swipe a waiting request to Search Now or Delete.
