# Track Summon — TestFlight beta copy

Track Summon is distributed **only through TestFlight**, not for general App Store
release. This file is the copy for the beta: the tester-facing description and
the App Review notes. Because it isn't going to general availability, it names
the actual moving parts (slskd, Plex, yt-dlp) plainly instead of talking around
them — the beta audience is self-hosters who run these tools already.

**Review exposure, by test type:**
- **Internal testing** (you + up to 100 users you add to your App Store Connect
  team) — **no Beta App Review**. Naming slskd/Soulseek here carries no risk.
  This is the intended distribution.
- **External testing** (email invites or a public link, up to 10,000) — goes
  through **Beta App Review**, which can scrutinize a Soulseek-backed tool. If
  you open external testing, expect possible pushback on the direct language
  below; keep it internal to avoid that entirely.

---

## App name
Track Summon

## Subtitle (30 char max)
Remote for your music server

## What to Test (tester-facing beta description)

Track Summon is a companion app for the self-hosted Track Summon server. Search for a
track, send a request, and your own server locates it, tags it, and files it
into your Plex library — then it's ready to play when you're home.

Before the app is useful you need the server side running:

• A Docker host (NAS, home server, mini PC)
• Plex, for your music library and playlists
• slskd — a Soulseek client — which Track Summon searches for each request
  (it also falls back to YouTube via yt-dlp when slskd comes up empty)

In this build, please try: connecting to your server, searching and requesting
a single track, requesting a whole album, a manual request with an exact title,
and adding a track to a playlist. Report anything that stalls, mis-tags, or
files to the wrong place.

Away from home, your phone must reach your server over a VPN (Tailscale,
WireGuard) or an HTTPS reverse proxy. You are responsible for the content you
request and for respecting copyright.

## App Review notes (only relevant if you enable EXTERNAL testing)

> Track Summon is a companion/remote-control app for a server the user runs on their
> own hardware — the same model as a Transmission remote or a Plex/Overseerr
> client. It performs no downloading, streaming, or file transfer on the device.
>
> The app cannot be exercised without a backend the reviewer supplies. On first
> launch it asks for a server address and access key; with no server it does
> nothing. A demo server can be provided on request:
>
>     Server address: https://<demo-host>
>     Access key:     <demo-key>
>
> On the server, requests are fulfilled by slskd (a Soulseek client) that the
> user installs and configures themselves, with a YouTube (yt-dlp) fallback. The
> app binary contains none of that — it only sends requests to the user's server
> and reads track metadata from public catalogs (Deezer, iTunes, MusicBrainz).
> Intended use is managing a personal music library; the user is responsible for
> the content they add.

## Age rating
4+ — no objectionable content in the app itself.

## Privacy — App Privacy answers
- **Data collection: None.** No analytics, accounts, ads, or third-party SDKs.
- Server address and access key are stored on device and sent only to the
  user's configured server — never to the developer or a third party.
- Search queries go to the user's server and public metadata APIs; nothing is
  stored or tied to identity.

## Encryption
`ITSAppUsesNonExemptEncryption` is set to `false` in Info.plist (standard HTTPS
only), so uploads won't prompt for export compliance.
