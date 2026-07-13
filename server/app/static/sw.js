/* Track Summon PWA service worker — caches the app shell, never the API. */
const CACHE = "ts-shell-v1";
const SHELL = [
  "/", "/index.html", "/styles.css", "/app.js", "/manifest.webmanifest",
  "/icon-192.png", "/icon-512.png", "/icon-180.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Never intercept API traffic — always hit the network.
  if (url.pathname.startsWith("/api/")) return;
  if (e.request.method !== "GET") return;
  // Cache-first for the shell, with a network fallback that refreshes the cache.
  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit || fetch(e.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return resp;
      }).catch(() => caches.match("/"))
    )
  );
});
