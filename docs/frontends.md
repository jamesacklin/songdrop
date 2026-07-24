# Frontends: iOS app & PWA

Songdrop ships two thin clients over the same server API: a native SwiftUI iOS app
(`ios/Songdrop/`) and a vanilla-JS installable PWA (`server/app/static/`, served at
`/`). Both are deliberately **remote controls** — no local catalog, no content of
their own; all state lives on the user's server. They are structurally parallel:
same three tabs (Search / Requests / Settings), same endpoints, same on-device
storage (server URL + access key + default playlist), same status/retry UX.

## iOS app

**Entry & tabs.** `SongdropApp` → `ContentView`, a `TabView` with **Search**,
**Requests** ("Downloads"), and **Settings**. On first launch (empty `serverURL`) it
presents `OnboardingView` as a full-screen cover.

**`APIClient`** is a stateless value type; `APIClient.shared` re-reads `serverURL`
and `apiKey` from `UserDefaults` on every access. It sets the `X-API-Key` header,
decodes with `.convertFromSnakeCase`, and percent-encodes `+` in query values (so
titles like "C++" or Ed Sheeran's "+" survive). Methods map 1:1 to the API:
`search`, `requests`, `clear`, `album`, `playlists`, `addRequest`, `bulkAdd`,
`retry`, `delete(id, purge:)`, `health`, `status`, `getConfig`, `saveConfig`.

> **Connection test uses `getConfig()`, not `health()`** — `/api/health` is
> unauthenticated and would pass with a wrong key, whereas `/api/config` requires the
> key, so a bad key surfaces as a `401` → "Wrong API key". This rationale is shared by
> onboarding and settings, on both clients.

**Models** (`Models.swift`) are `Codable`: `SearchResult` (with `isDeezer`),
`TrackRequest` (with computed `isInFlight`/`isDeletable`/`isRetryable` from the status
string), `RequestsResponse` (carries server `now` for countdown clock-skew),
`NewRequest`, `AlbumTrack`/`AlbumResponse`, `BulkResponse`, `ServerStatus`/`ServerConfig`.

**Views:**
- **SearchView** — `.searchable`, results as tappable rows; clearing the field resets
  to the initial empty state. Tapping a result opens `AddRequestSheet`; a "request
  manually" row opens `ManualRequestSheet`. On add, jumps to the Requests tab.
- **RequestsView** — the Downloads list, polled every 4s (only while visible). Shows a
  banner when slskd is down. Per-row **swipe actions**: *Search Now* (retry) for
  failed/waiting; for a completed row with a file, *Delete File* (→ confirmation →
  `delete(purge:true)`, removing file + Plex + playlist) and *Clear Entry* (soft
  delete); else plain *Delete*. A toolbar menu clears completed/failed. A
  `TimelineView`-driven **live countdown** ("next search in M:SS", corrected by the
  server `now` offset) shows on waiting rows.
- **AddRequestSheet / AlbumTracksView** — the add sheet starts at `.medium`; drilling
  into "View Full Album" forces `.large` and **snaps back** on pop (the full-height
  behavior). AlbumTracksView loads the MusicBrainz/Deezer tracklist and offers
  per-track add or **"Request All"** (chunked into bulk calls of ≤100). Deezer results
  send `deezer_id`; iTunes results send `cover_url`/`track_no`/`year`.
- **ManualRequestSheet** — freeform artist/title/album plus a **`youtube_url`** field
  (grab from an exact video, skipping Soulseek).
- **SettingsView** — server URL + access key (Test Connection), plus slskd and Plex
  sections that load from and save to `/api/config` (server-side; creds are never
  stored on-device), each with its own Save & Test that re-probes `/api/status`.
- **OnboardingView** — honest first-run framing ("a companion app… does nothing until
  connected… you're responsible for what you add and for respecting copyright").

**On-device storage** is three `@AppStorage` (UserDefaults) keys — `serverURL`,
`apiKey`, `defaultPlaylist`. No Keychain; slskd/Plex creds live only server-side.

## PWA (`server/app/static/`)

A single-page, no-framework, no-build app that mirrors the iOS UI. `index.html` is a
shell (onboarding screen + `#app` with three `<section>` views and a bottom tab bar).
`app.js` builds all DOM by hand via an `h(tag, props, ...kids)` helper, keeps state in
module-level `let`s, and its `API.*` object hits the exact same routes (payloads stay
snake_case; the server accepts them). It reimplements the iOS views — search, add
sheet, album sheet with chunked "Request All", manual sheet with `youtube_url`,
requests list with an action-sheet row menu, a 1s countdown ticker, and settings.

> The **YouTube-fallback toggle** (`ytdlp_enabled`) and the read-only **storage paths**
> panel (Downloads / Library / Plex-reads, for diagnosing volume mistakes) live in the
> PWA's settings (`renderExtras()`), not in the iOS Settings screen.

**Service worker** (`sw.js`, cache `ts-shell-v1`): cache-first for the app shell with
background refresh, and it **explicitly never intercepts `/api/`** ("always hit the
network") — so the UI is installable/offline-capable but data is always live.

**Manifest** (`manifest.webmanifest`): `display: standalone`, portrait, 192/512 +
maskable icons — installable to the home screen.

**Storage keys:** `ts_url`, `ts_key`, `ts_playlist` (the PWA analogues of the iOS
`@AppStorage` keys). On boot, if either URL or key is missing it shows onboarding,
prefilling the server field with `window.location.origin` (so visiting the server in a
browser is the whole install). Styling (`styles.css`) is an iOS-flavored design system
of CSS custom properties with light/dark support.

## iOS ↔ PWA parity

| Concern | iOS | PWA |
| --- | --- | --- |
| Server URL / key / playlist | `@AppStorage serverURL/apiKey/defaultPlaylist` | `localStorage ts_url/ts_key/ts_playlist` |
| Auth | `X-API-Key` | `X-API-Key` |
| Connection test | `getConfig()` (needs key) | `getConfig()` (needs key) |
| Requests poll | 4s | 4s |
| Status poll throttle | 30s | 30s |
| Countdown | `TimelineView` 1s | `setInterval` 1s |
| Bulk chunk | 100 | 100 |
| Purge (file + Plex + playlist) | `delete(purge:true)` | `del(id, true)` |
| 409 ("worker already claimed") | caught silently | ignored (`status !== 409`) |
