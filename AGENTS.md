# AGENTS.md

Operational guide for working on **Songdrop** — a song-first request system for a
self-hosted music library. This file captures the non-obvious build/ship/deploy
knowledge and gotchas. No secrets live here; see **Secrets** at the bottom for
where they actually live.

> **📐 Architecture:** before making non-trivial changes, read how the system
> actually works — the API, the acquisition pipeline, the frontends, and deployment
> — in [`docs/`](docs/README.md). Start with [`docs/README.md`](docs/README.md).
> This file is the terse command-level quick-reference; the docs are the deep dive.

## What it is

Search a track on your phone/PWA → the server acquires it via slskd (Soulseek)
with a YouTube (yt-dlp) fallback → tags it (mutagen) → files it into a Plex music
library → optional playlist add → optional ntfy push.

Naming: the product is **Songdrop**. (It was briefly renamed "Track Summon" to
dodge an App Store name collision, then reverted.) The iOS home-screen name is
**Songdrop**; the App Store Connect *listing* name is **"Songdrop - Track Request"**
(the bare "Songdrop" title was taken).

## Repo layout

- `server/` — FastAPI app (async, SQLite queue + background worker). Also serves
  the PWA at `/` from `server/app/static/`. Dockerfile builds the published image.
- `ios/` — SwiftUI app (iOS 17+), generated from `project.yml` via XcodeGen.
  `ios/fastlane/` has the TestFlight build/upload lanes.
- `site/` — single-file marketing site (`index.html`, system-sans on white).
- `docker-compose.yml` — runs slskd + Songdrop together for local/self-host use.
- `deploy-site.sh` — deploys `site/` to Cloudflare Pages.
- `README.md` — user-facing setup docs.

## Server / Docker

- Published image: **`jamesacklin/songdrop`** on Docker Hub (`:latest` + a version
  tag), **multi-arch** (linux/amd64 + linux/arm64), public.
- Publish with buildx multi-arch (Docker Desktop must be running; a
  `docker-container` builder is required for multi-arch):
  ```sh
  docker buildx build --builder <container-builder> \
    --platform linux/amd64,linux/arm64 \
    -t jamesacklin/songdrop:<ver> -t jamesacklin/songdrop:latest \
    --push server/
  ```
  A freshly-pushed Docker Hub repo defaults to **private** — flip it to public in
  the Hub UI or `docker pull` fails for everyone.
- **Volumes (get these right):** `/data` (SQLite queue + auto-generated access
  key — persist it), `/music` (**must be the exact folder Plex scans**, else
  tracks file but never appear in Plex), `/downloads` (the folder slskd writes to).
  If Plex sees the library at a different container path, set `PLEX_LIBRARY_DIR`.
- Config: env vars, or runtime via `GET/PUT /api/config` (persisted in the DB,
  overrides env). Access key auto-generates on first boot (printed to logs) unless
  `SONGDROP_API_KEY` is set. `/api/health` is unauthenticated; everything else
  needs `X-API-Key`.

## Deployment (TrueNAS SCALE)

- The production instance runs as a TrueNAS **custom app** named `songdrop`,
  pulling `jamesacklin/songdrop:latest` (it previously ran from bind-mounted
  source; switched to the published image).
- TrueNAS host is reachable over Tailscale. Its API is JSON-RPC over WebSocket at
  `ws://<host>/api/current`; authenticate with `auth.login_with_api_key`.
- Redeploy = update the custom-app compose and wait for the job:
  `app.update("songdrop", {custom_compose_config: {...}})` returns a job id →
  poll `core.get_jobs [["id","=",<jid>]]` until `SUCCESS`. Then the app pulls the
  new image and restarts. `app.config("songdrop")` returns the current compose.
- The app's env (Plex/slskd creds, `SONGDROP_API_KEY`) lives in the TrueNAS app
  config, **not** in this repo. `PLEX_LIBRARY_DIR` is set because Plex mounts the
  same host music folder at a different container path than Songdrop does.

## Marketing site (Cloudflare Pages)

- `site/index.html` + `site/editorial.css` — styled with the **`@ackl/editorial`**
  design system (vendored into `editorial.css`; left-aligned, Arimo, dark-mode
  aware). No build step. `index.html` links `./editorial.css` and uses its
  `--ed-*` CSS variables, so **both files must ship together** (an earlier plain
  centered layout was replaced by this via PR #1).
- Hosted on a Cloudflare Pages project named **`songdrop`**, custom domain
  **`songdrop.ackl.in`** (zone `ackl.in`), proxied CNAME → `songdrop.pages.dev`.
- Redeploy: `CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… ./deploy-site.sh`
  (uses `npx wrangler pages deploy site` — deploys the whole `site/` dir, so
  `editorial.css` goes too). The token needs Account · Cloudflare Pages · Edit
  (plus Zone · DNS · Edit + Zone · Read on `ackl.in` to manage the domain).
- The TestFlight join link in the page must match the current app's TestFlight.

## iOS / TestFlight

- Build the project first: `cd ios && xcodegen generate` (the `.xcodeproj` is
  gitignored — always regenerate from `project.yml`).
- **Bundle ID: `com.jamesacklin.songdropapp`.** ⚠️ Do **not** use
  `com.jamesacklin.songdrop` — that id was permanently burned when an earlier
  App Store Connect app on it was deleted (Apple never lets a deleted app's bundle
  id be reused; it won't appear in the New App dropdown).
- **Two Apple teams — don't mix them up:**
  - `FTFY9QQ2XQ` — **paid** Developer Program team ("James Acklin", ASC provider
    `142171647`). Owns the App Store Connect app, the bundle id, the distribution
    cert, and the API key. Use this for everything distribution.
  - `4S2D335HW6` — the free personal team (dev-only). `project.yml` still lists it
    as `DEVELOPMENT_TEAM`; the fastlane lane overrides signing to `FTFY9QQ2XQ`.
  - The App Store Connect account is **James Acklin** (`142171647`), **not** Tlon
    Corporation — the same Apple ID can access both; pick the personal one.
- **Shipping to TestFlight** (`ios/fastlane/Fastfile`, two lanes):
  ```sh
  cd ios
  export ASC_KEY_ID=… ASC_ISSUER_ID=… \
         ASC_KEY_PATH=~/.appstoreconnect/private_keys/AuthKey_<id>.p8
  fastlane build     # dist cert + App Store profile + signed .ipa
  fastlane upload     # upload_to_testflight via the API key
  ```
  Bump `MARKETING_VERSION` + `CURRENT_PROJECT_VERSION` in `project.yml` per release.
  Export compliance is pre-answered (`ITSAppUsesNonExemptEncryption=false`).

### iOS gotchas (all hit during first ship)

1. **App records can't be created programmatically.** The ASC API forbids it
   (`apps` disallows CREATE) and fastlane `produce` needs an Apple ID login. You
   must create the app manually in App Store Connect (New App → pick the bundle
   id). Bundle-id registration *can* be done via the API (`POST /v1/bundleIds`).
2. **codesign hangs on a keychain prompt** on a headless/first-time machine. Fix:
   import the distribution cert+key into a dedicated keychain with a *known*
   password, then
   `security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <pw> <kc>`
   and put it first in `security list-keychains -d user -s`. The `.p12` fastlane
   `cert` leaves behind holds only the key — import the `.cer` too to form an
   identity.
3. **Xcode 16+ profile location.** Profiles must be in
   `~/Library/Developer/Xcode/UserData/Provisioning Profiles/`; fastlane `sigh`
   installs to the legacy `~/Library/MobileDevice/...`. The Fastfile copies it.
4. Freshly created / Xcode-managed ("XC …") bundle ids can lag before showing in
   the New App dropdown; renaming the identifier via the API nudges it.

## Secrets (never commit these)

None are in the repo. Where they live:

- **ASC API key** (`.p8`): `~/.appstoreconnect/private_keys/AuthKey_<id>.p8`
  (local only; Apple lets you download it once — regenerate if lost). The `.p8`
  is the secret; the key id / issuer id are not.
- **Plex token, slskd creds, `SONGDROP_API_KEY`**: in the TrueNAS app config and
  the local `.env` for compose (`.env` is gitignored; see `.env.example`).
- **Cloudflare API token / account id**: passed to `deploy-site.sh` via env.
- **TrueNAS API key**: provide at deploy time; not stored in the repo.

Signing artifacts (`ios/*.p12`, `*.cer`, `*.mobileprovision`, `ios/build/`) and
fastlane run output are gitignored — keep them out of commits.
