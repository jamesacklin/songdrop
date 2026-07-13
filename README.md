# Track Summon

Song-first requests for a self-hosted music library. Shazam a track at a coffee
shop, open the app, search, tap **Add to Library** — and the next time you're
home it's in Plex, properly tagged, with album art, in the playlist you asked for.

The flow (as described in [Joe Karlsson's post](https://www.joekarlsson.com/blog/self-hosted-music-still-sucks-in-2026/)):

```
iOS app ──▶ Track Summon server ──▶ slskd (Soulseek) ──▶ tag (mutagen) ──▶ Plex library
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

```bash
cp .env.example .env
# fill in SLSKD_API_KEY, SONGDROP_API_KEY, MUSIC_LIBRARY_PATH, PLEX_URL, PLEX_TOKEN
docker compose up -d --build
```

Notes:

- **slskd**: on first run, open http://your-server:5030, log in, and add your Soulseek
  credentials. For Track Summon's access, either create an API key (Options → Web →
  Authentication → API keys) and set `SLSKD_API_KEY`, or set
  `SLSKD_USERNAME`/`SLSKD_PASSWORD` to the web UI login (Track Summon handles the JWT
  session itself). If you already run slskd (e.g. alongside Lidarr), delete the
  `slskd` service from the compose file and point `SLSKD_URL` at your existing instance —
  just make sure Track Summon can see slskd's completed-downloads folder at
  `SLSKD_DOWNLOADS_DIR`.
- **Plex token**: any signed-in Plex Web session → open an item → Get Info → View XML →
  copy the `X-Plex-Token` from the URL.
- **Path mapping**: `MUSIC_LIBRARY_DIR` is the library as *Track Summon* sees it (`/music`
  in the container). If Plex sees that same folder at a different path, set
  `PLEX_LIBRARY_DIR` so partial scans target the right directory.
- **Lidarr coexistence**: Track Summon writes normal `Artist/Album/NN - Title.ext` files, so
  it lives happily next to a Lidarr-managed library. Keep Lidarr for full-album/artist
  monitoring; use Track Summon for one-off tracks.

Run without Docker if you prefer:

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SLSKD_URL=... SLSKD_API_KEY=... MUSIC_LIBRARY_DIR=... \
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
