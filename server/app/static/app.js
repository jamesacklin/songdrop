"use strict";
/* Songdrop PWA — mirrors the iOS front-end. Vanilla JS, no dependencies. */

// ---------- state ----------
const LS = window.localStorage;
let baseURL = LS.getItem("ts_url") || "";
let apiKey = LS.getItem("ts_key") || "";
let defaultPlaylist = LS.getItem("ts_playlist") || "";
let clockOffset = 0;              // server time − device time (seconds)
let currentTab = "search";
let reqTimer = null, statusTimer = null, tickTimer = null, lastStatusAt = 0;
let cachedStatus = null;

// ---------- tiny DOM helper ----------
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  if (props) for (const k in props) {
    if (k === "class") e.className = props[k];
    else if (k === "html") e.innerHTML = props[k];
    else if (k.startsWith("on") && typeof props[k] === "function") e.addEventListener(k.slice(2), props[k]);
    else if (props[k] != null) e.setAttribute(k, props[k]);
  }
  for (const kid of kids.flat()) if (kid != null) e.append(kid.nodeType ? kid : document.createTextNode(kid));
  return e;
}
const $ = (s) => document.querySelector(s);
const esc = (s) => (s ?? "").toString();

// status glyphs (approximate SF Symbols)
const SVG = {
  check: '<svg viewBox="0 0 24 24" width="24" height="24" fill="var(--green)"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm-1.2 14.2l-4-4 1.4-1.4 2.6 2.6 5.6-5.6 1.4 1.4-7 7z"/></svg>',
  x: '<svg viewBox="0 0 24 24" width="24" height="24" fill="var(--red)"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm3.5 12.1l-1.4 1.4L12 13.4l-2.1 2.1-1.4-1.4L10.6 12 8.5 9.9l1.4-1.4L12 10.6l2.1-2.1 1.4 1.4L13.4 12l2.1 2.1z"/></svg>',
  clock: '<svg viewBox="0 0 24 24" width="22" height="22" fill="var(--label-3)"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm1 10.5V6h-2v7.5l5 3 1-1.7-4-2.3z"/></svg>',
  retryc: '<svg viewBox="0 0 24 24" width="22" height="22" fill="var(--orange)"><path d="M12 4V1L8 5l4 4V6a6 6 0 11-6 6H4a8 8 0 108-8z"/></svg>',
  chev: '<svg viewBox="0 0 12 20" width="9" height="15" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M2 2l8 8-8 8"/></svg>',
  plus: '<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm1 9h4v2h-4v4h-2v-4H7v-2h4V7h2v4z"/></svg>',
  note: '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M9 17V5l10-2v12"/><circle cx="6.5" cy="17.5" r="2.6"/><circle cx="16.5" cy="15.5" r="2.6"/></svg>',
};

// ---------- api ----------
async function api(path, opts = {}) {
  const url = (baseURL.replace(/\/$/, "")) + path;
  const headers = Object.assign({}, opts.headers);
  if (apiKey) headers["X-API-Key"] = apiKey;
  if (opts.body) headers["Content-Type"] = "application/json";
  const res = await fetch(url, { ...opts, headers });
  if (!res.ok) {
    let msg = "";
    try { msg = (await res.json()).detail || ""; } catch { try { msg = await res.text(); } catch {} }
    const e = new Error(msg || ("Server error " + res.status));
    e.status = res.status;
    throw e;
  }
  if (res.status === 204) return null;
  return res.json();
}
const API = {
  health: () => api("/api/health"),
  status: () => api("/api/status"),
  getConfig: () => api("/api/config"),
  saveConfig: (c) => api("/api/config", { method: "PUT", body: JSON.stringify(c) }),
  search: (q) => api("/api/search?q=" + encodeURIComponent(q)).then(r => r.results),
  album: (a, al) => api("/api/album?artist=" + encodeURIComponent(a) + "&album=" + encodeURIComponent(al)),
  playlists: () => api("/api/playlists").then(r => r.playlists),
  requests: () => api("/api/requests"),
  add: (b) => api("/api/requests", { method: "POST", body: JSON.stringify(b) }),
  bulk: (list) => api("/api/requests/bulk", { method: "POST", body: JSON.stringify({ requests: list }) }),
  retry: (id) => api("/api/requests/" + id + "/retry", { method: "POST" }),
  del: (id, purge) => api("/api/requests/" + id + (purge ? "?purge=true" : ""), { method: "DELETE" }),
  clear: (statuses) => api("/api/requests/clear", { method: "POST", body: JSON.stringify({ statuses }) }),
};

// ---------- toast ----------
let toastT;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 2200);
}

// ---------- sheets ----------
function openSheet(buildBody, title, opts = {}) {
  const sheet = $("#sheet"), scrim = $("#scrim");
  sheet.innerHTML = "";
  const nav = h("div", { class: "sheet-nav" },
    h("button", { class: "nav-btn", onclick: closeSheet }, opts.back ? "‹ Back" : "Cancel"),
    h("div", { class: "title" }, title || ""),
    opts.confirm
      ? h("button", { class: "nav-btn bold", id: "sheet-confirm", onclick: opts.confirm.onclick }, opts.confirm.label)
      : h("div", { style: "width:52px" })
  );
  const grab = h("div", { class: "grabber" });
  const body = h("div", { class: "sheet-body" });
  buildBody(body);
  sheet.append(grab, nav, body);
  scrim.classList.remove("hidden");
  requestAnimationFrame(() => { scrim.classList.add("show"); sheet.classList.add("show"); });
  scrim.onclick = closeSheet;
}
function closeSheet() {
  const sheet = $("#sheet"), scrim = $("#scrim");
  sheet.classList.remove("show"); scrim.classList.remove("show");
  setTimeout(() => { scrim.classList.add("hidden"); sheet.innerHTML = ""; }, 300);
}
// action sheet (iOS-style list of choices)
function actionSheet(title, actions) {
  openSheet((body) => {
    const grp = h("div", { class: "group", style: "margin-top:4px" });
    actions.forEach(a => grp.append(h("button", {
      class: "cellbtn center" + (a.destructive ? " destructive" : ""),
      style: a.destructive ? "color:var(--red)" : "",
      onclick: () => { closeSheet(); setTimeout(a.onclick, 260); }
    }, a.label)));
    body.append(grp);
  }, title);
}

// ---------- playlist picker control ----------
function playlistControl(playlists, initial) {
  const state = { value: initial || "" };
  const sel = h("select", { class: "v", style: "text-align:right;color:var(--tint);border:0;background:none;-webkit-appearance:none;appearance:none;max-width:60%" });
  sel.append(h("option", { value: "" }, "None"));
  playlists.forEach(p => sel.append(h("option", { value: p, selected: p === state.value ? "" : null }, p)));
  sel.append(h("option", { value: "__new__" }, "New playlist…"));
  const newInput = h("input", { class: "v", placeholder: "New playlist name", style: "display:none" });
  sel.value = playlists.includes(state.value) ? state.value : "";
  sel.addEventListener("change", () => { newInput.style.display = sel.value === "__new__" ? "block" : "none"; });
  const rows = [
    h("div", { class: "srow" }, h("label", { class: "k" }, "Playlist"), sel),
    h("div", { class: "srow full", id: "np-row", style: "display:none" }, newInput),
  ];
  rows[1] = h("div", { class: "srow full" }); rows[1].append(newInput);
  rows[1].style.display = "none";
  sel.addEventListener("change", () => { rows[1].style.display = sel.value === "__new__" ? "block" : "none"; });
  state.get = () => {
    if (sel.value === "__new__") { const n = newInput.value.trim(); return n || null; }
    return sel.value || null;
  };
  return { rows, get: state.get };
}

// ---------- Search view ----------
let searchResults = [], searchDone = false, searchQuery = "", searching = false;
function renderSearch() {
  const v = $("#view-search"); v.innerHTML = "";
  v.append(
    h("div", { class: "nav" }, h("div", { class: "nav-row" }, h("h1", {}, "Songdrop"))),
    h("div", { class: "searchbar" },
      h("input", {
        type: "search", placeholder: "Song, artist…", value: searchQuery,
        enterkeyhint: "search", autocapitalize: "off",
        oninput: (e) => { searchQuery = e.target.value; if (!searchQuery.trim()) { searchResults = []; searchDone = false; renderSearchBody(); } },
        onkeydown: (e) => { if (e.key === "Enter") runSearch(); },
      })
    ),
    h("div", { id: "search-body" })
  );
  renderSearchBody();
}
function renderSearchBody() {
  const b = $("#search-body"); if (!b) return; b.innerHTML = "";
  if (searching) { b.append(h("div", { class: "center-fill" }, h("div", { class: "spinner lg" }), "Searching…")); return; }
  if (!searchResults.length) {
    if (searchDone) {
      b.append(h("div", { class: "center-fill" },
        h("div", { class: "ic" }, "⌕"),
        h("div", { class: "big" }, "No matches"),
        h("div", { class: "empty-sub" }, "Neither Deezer nor iTunes lists this one — but Soulseek might. Request it manually with the exact artist and title."),
        h("button", { class: "btn", style: "width:auto;padding:10px 20px", onclick: () => openManualSheet(searchQuery) }, "Request Manually")));
    } else {
      b.append(h("div", { class: "center-fill" },
        h("div", { class: "ic", html: SVG.note }),
        h("div", { class: "big" }, "Find a song"),
        h("div", { class: "empty-sub" }, "Search by song title, artist, or both — e.g. “Midnight City M83”.")));
    }
    return;
  }
  const list = h("ul", { class: "list plain" });
  searchResults.forEach(t => {
    list.append(h("li", { class: "row tappable", onclick: () => openAddSheet(t) },
      artEl(t.cover),
      h("div", { class: "txt" },
        h("div", { class: "t1" }, t.title),
        h("div", { class: "t2" }, t.artist),
        h("div", { class: "t3" }, t.album)),
      h("div", { class: "accessory", html: SVG.plus })));
  });
  list.append(h("li", { class: "row tappable", onclick: () => openManualSheet(searchQuery) },
    h("div", { class: "txt", style: "color:var(--tint)" }, "Not here? Request manually…")));
  b.append(list);
}
function artEl(url) {
  if (url) return h("img", { class: "art", src: url, loading: "lazy", alt: "" });
  return h("div", { class: "art", html: SVG.note });
}
async function runSearch() {
  const q = searchQuery.trim(); if (!q) return;
  searching = true; renderSearchBody();
  try { searchResults = await API.search(q); searchDone = true; }
  catch (e) { toast(e.message); }
  finally { searching = false; renderSearchBody(); }
}

// ---------- Add sheet ----------
async function openAddSheet(track) {
  const playlists = await API.playlists().catch(() => []);
  const pc = playlistControl(playlists, defaultPlaylist);
  let submitting = false;
  const submit = async () => {
    if (submitting) return; submitting = true;
    const cbtn = $("#sheet-confirm"); if (cbtn) cbtn.innerHTML = ""; if (cbtn) cbtn.append(h("div", { class: "spinner" }));
    const isDeezer = (track.source || "deezer") === "deezer";
    const pl = pc.get();
    try {
      await API.add({
        artist: track.artist, title: track.title,
        album: track.album || null,
        deezer_id: isDeezer ? track.id : null,
        playlist: pl,
        cover_url: isDeezer ? null : track.cover_xl,
        track_no: isDeezer ? null : track.track_no,
        year: isDeezer ? null : track.year,
      });
      if (pl) { defaultPlaylist = pl; LS.setItem("ts_playlist", pl); }
      closeSheet(); toast("Added to your library"); goTab("requests");
    } catch (e) { submitting = false; toast(e.message); if (cbtn) { cbtn.textContent = "Add"; } }
  };
  openSheet((body) => {
    body.append(h("div", { class: "group", style: "margin:6px 16px 0" },
      h("div", { class: "row" }, artEl(track.cover),
        h("div", { class: "txt" }, h("div", { class: "t1" }, track.title),
          h("div", { class: "t2" }, track.artist), h("div", { class: "t3" }, track.album)))));
    if (track.album) {
      body.append(h("div", { class: "group", style: "margin-top:20px" },
        h("button", { class: "cellbtn", onclick: () => openAlbumSheet(track.artist, track.album, pc.get) },
          h("span", { style: "display:flex;align-items:center;justify-content:space-between" },
            h("span", {}, "View Full Album"), h("span", { class: "chev", html: SVG.chev })))),
        h("div", { class: "section-ftr" }, "The complete tracklist — including versions streaming services leave out."));
    }
    body.append(h("div", { class: "section-hdr" }, "Playlist (optional)"),
      h("div", { class: "group" }, ...pc.rows));
  }, "Add to Library", { confirm: { label: "Add", onclick: submit } });
}

// ---------- Manual request sheet ----------
async function openManualSheet(prefillTitle) {
  const playlists = await API.playlists().catch(() => []);
  const pc = playlistControl(playlists, defaultPlaylist);
  const artist = h("input", { class: "v", placeholder: "Artist (required)", autocapitalize: "words" });
  const title = h("input", { class: "v", placeholder: "Song title (required)", value: prefillTitle || "", autocapitalize: "words" });
  const album = h("input", { class: "v", placeholder: "Album (optional)", autocapitalize: "words" });
  const yturl = h("input", { class: "v", placeholder: "YouTube URL (optional)", inputmode: "url", autocapitalize: "off" });
  let submitting = false;
  const submit = async () => {
    if (submitting) return;
    if (!artist.value.trim() || !title.value.trim()) { toast("Artist and title are required"); return; }
    submitting = true;
    const pl = pc.get();
    try {
      await API.add({
        artist: artist.value.trim(), title: title.value.trim(),
        album: album.value.trim() || null, deezer_id: null, playlist: pl,
        youtube_url: yturl.value.trim() || null,
      });
      if (pl) { defaultPlaylist = pl; LS.setItem("ts_playlist", pl); }
      closeSheet(); toast("Request added"); goTab("requests");
    } catch (e) { submitting = false; toast(e.message); }
  };
  openSheet((body) => {
    body.append(
      h("div", { class: "group", style: "margin-top:6px" },
        h("div", { class: "srow full" }, artist),
        h("div", { class: "srow full" }, title),
        h("div", { class: "srow full" }, album)),
      h("div", { class: "section-ftr" }, "The Soulseek search uses the artist and exact title — include qualifiers like “(Indifferent Remix)” for a specific version."),
      h("div", { class: "group", style: "margin-top:20px" }, h("div", { class: "srow full" }, yturl)),
      h("div", { class: "section-ftr" }, "Paste a YouTube link to grab audio from that exact video, skipping the Soulseek search. Otherwise YouTube is only used automatically when Soulseek comes up empty."),
      h("div", { class: "section-hdr" }, "Playlist (optional)"),
      h("div", { class: "group" }, ...pc.rows));
  }, "Manual Request", { confirm: { label: "Add", onclick: submit } });
}

// ---------- Album sheet ----------
function openAlbumSheet(artist, albumName, getPlaylist) {
  const requested = new Set();
  openSheet(async (body) => {
    body.append(h("div", { class: "center-fill" }, h("div", { class: "spinner lg" }), "Looking up album…"));
    let album;
    try { album = await API.album(artist, albumName); }
    catch (e) { body.innerHTML = ""; body.append(h("div", { class: "center-fill" }, h("div", { class: "big" }, "Album not found"), h("div", { class: "empty-sub" }, e.message))); return; }
    body.innerHTML = "";
    body.append(h("div", { class: "group", style: "margin:6px 16px 0" },
      h("div", { class: "row" }, artEl(album.cover),
        h("div", { class: "txt" }, h("div", { class: "t1" }, album.title), h("div", { class: "t2" }, album.artist),
          h("div", { class: "t3" }, [album.year, (album.tracks.length + " tracks"), album.source === "musicbrainz" ? "via MusicBrainz" : null].filter(Boolean).join(" · "))))));
    const allBtn = h("button", { class: "cellbtn center", onclick: () => requestAll() }, "Request All " + album.tracks.length + " Tracks");
    body.append(h("div", { class: "group", style: "margin-top:14px" }, allBtn));
    const summary = h("div", { class: "section-ftr" });
    body.append(summary);
    const list = h("ul", { class: "list", style: "margin-top:14px" });
    const grp = h("div", { class: "group" });
    album.tracks.forEach(tr => {
      const acc = h("div", { class: "accessory", html: SVG.plus });
      const row = h("div", { class: "row tappable", onclick: () => reqOne(tr, row, acc) },
        h("div", { style: "width:24px;text-align:right;color:var(--label-3);font-size:14px" }, String(tr.position)),
        h("div", { class: "txt" }, h("div", { class: "t1" }, tr.title)), acc);
      grp.append(row);
    });
    list.append(grp); body.append(list);

    async function reqOne(tr, row, acc) {
      if (requested.has(tr.position)) return;
      acc.innerHTML = ""; acc.append(h("div", { class: "spinner" }));
      try {
        await API.add({ artist: album.artist, title: tr.title, album: album.title, deezer_id: null,
          playlist: getPlaylist(), cover_url: album.cover_xl, track_no: tr.track_no || tr.position, year: album.year, disc_no: tr.disc_no });
        requested.add(tr.position); acc.innerHTML = SVG.check;
      } catch (e) { acc.innerHTML = SVG.plus; toast(e.message); }
    }
    async function requestAll() {
      allBtn.innerHTML = ""; allBtn.append(h("div", { class: "spinner" }));
      const pending = album.tracks.filter(t => !requested.has(t.position));
      const batch = pending.map(t => ({ artist: album.artist, title: t.title, album: album.title, deezer_id: null,
        playlist: getPlaylist(), cover_url: album.cover_xl, track_no: t.track_no || t.position, year: album.year, disc_no: t.disc_no }));
      let created = 0, skipped = 0;
      try {
        for (let i = 0; i < batch.length; i += 100) {
          const r = await API.bulk(batch.slice(i, i + 100)); created += r.created; skipped += r.skipped;
        }
        pending.forEach(t => requested.add(t.position));
        summary.textContent = "Queued " + created + " track" + (created === 1 ? "" : "s") + (skipped ? " — " + skipped + " already requested or in your library" : "") + ".";
        allBtn.textContent = "All Tracks Requested";
        goTabSoon();
      } catch (e) { allBtn.textContent = "Request All " + album.tracks.length + " Tracks"; toast(e.message); }
    }
    function goTabSoon() {}
  }, albumName, { back: true });
}

// ---------- Requests view ----------
let reqData = [], reqLoaded = false, reqLoadErr = null;
function renderRequests() {
  const v = $("#view-requests"); v.innerHTML = "";
  const canClear = reqData.some(r => r.status === "done" || r.status === "failed");
  v.append(h("div", { class: "nav" }, h("div", { class: "nav-row" },
    h("h1", {}, "Requests"),
    h("button", { class: "nav-btn", disabled: canClear ? null : "", onclick: openClearMenu }, "Clear"))));
  const body = h("div", { id: "requests-body" });
  v.append(body);
  renderRequestsBody();
}
function openClearMenu() {
  actionSheet("Clear finished requests", [
    { label: "Clear Completed", onclick: () => doClear(["done"]) },
    { label: "Clear Failed", onclick: () => doClear(["failed"]) },
    { label: "Clear Completed & Failed", onclick: () => doClear(["done", "failed"]) },
  ]);
}
async function doClear(statuses) {
  try { await API.clear(statuses); await loadRequests(); } catch (e) { toast(e.message); }
}
function renderRequestsBody() {
  const b = $("#requests-body"); if (!b) return; b.innerHTML = "";
  if (cachedStatus && cachedStatus.slskd && !cachedStatus.slskd.ok) {
    b.append(h("div", { class: "banner" }, h("div", { class: "b-ic" }, "⚠"),
      h("div", {}, h("div", { class: "b-t" }, "slskd is unreachable"),
        h("div", { class: "b-d" }, cachedStatus.slskd.detail || "Requests will keep retrying until it's back."))));
  }
  if (!reqData.length) {
    if (reqLoadErr && reqLoaded) b.append(h("div", { class: "center-fill" }, h("div", { class: "ic" }, "⚠"), h("div", { class: "big" }, "Can't reach the server"), h("div", { class: "empty-sub" }, reqLoadErr)));
    else if (reqLoaded) b.append(h("div", { class: "center-fill" }, h("div", { class: "ic" }, "▦"), h("div", { class: "big" }, "No requests yet"), h("div", { class: "empty-sub" }, "Songs you add from Search will show up here.")));
    else b.append(h("div", { class: "center-fill" }, h("div", { class: "spinner lg" })));
    return;
  }
  const list = h("ul", { class: "list plain" });
  reqData.forEach(r => list.append(requestRow(r)));
  b.append(list);
}
function requestRow(r) {
  const badge = statusBadge(r.status);
  const sub = h("div", { class: "t3" });
  fillSubtitle(sub, r);
  const txt = h("div", { class: "txt" }, h("div", { class: "t1" }, r.title), h("div", { class: "t2" }, r.artist), sub);
  if (r.playlist) txt.append(h("div", { class: "t3", style: "color:var(--label-2)" }, "♪ " + r.playlist));
  return h("li", { class: "row tappable", onclick: () => openRowActions(r) }, h("div", { class: "badge-wrap", style: "width:30px;display:flex;justify-content:center" }, badge), txt);
}
function statusBadge(status) {
  if (status === "done") return h("span", { class: "badge", html: SVG.check });
  if (status === "failed") return h("span", { class: "badge", html: SVG.x });
  if (status === "queued") return h("span", { class: "badge", html: SVG.clock });
  if (status === "waiting") return h("span", { class: "badge", html: SVG.retryc });
  return h("span", { class: "spinner" });
}
function fillSubtitle(el, r) {
  el.dataset.rid = r.id;
  if (r.status === "failed") { el.style.color = "var(--red)"; el.textContent = r.error || "Failed"; }
  else if (r.status === "waiting") { el.style.color = "var(--orange)"; el.dataset.waiting = "1"; el.dataset.retry = r.next_retry_at || ""; el.dataset.count = r.retry_count || 0; el.textContent = countdownText(r.next_retry_at, r.retry_count); }
  else { el.style.color = ""; el.textContent = r.detail || ""; }
}
function countdownText(nextRetryAt, count) {
  const attempt = count > 0 ? " (searched " + count + "×)" : "";
  if (!nextRetryAt) return "No results yet — will search again" + attempt;
  const remaining = Math.round(nextRetryAt - (Date.now() / 1000 + clockOffset));
  if (remaining <= 0) return "No results yet — searching again now…" + attempt;
  const m = Math.floor(remaining / 60), s = remaining % 60;
  return "No results yet — next search in " + m + ":" + String(s).padStart(2, "0") + attempt;
}
function tickCountdowns() {
  if (currentTab !== "requests") return;
  document.querySelectorAll('.t3[data-waiting="1"]').forEach(el => {
    el.textContent = countdownText(Number(el.dataset.retry) || null, Number(el.dataset.count) || 0);
  });
}
function openRowActions(r) {
  const actions = [];
  if (r.status === "failed" || r.status === "waiting")
    actions.push({ label: "Search Now", onclick: async () => { try { await API.retry(r.id); await loadRequests(); } catch (e) { if (e.status !== 409) toast(e.message); await loadRequests(); } } });
  const deletable = ["queued", "done", "failed", "waiting"].includes(r.status);
  if (r.status === "done" && r.file_path) {
    actions.push({ label: "Delete File from Disk & Plex", destructive: true, onclick: () => confirmPurge(r) });
    actions.push({ label: "Clear Entry", onclick: async () => { try { await API.del(r.id, false); await loadRequests(); } catch (e) { toast(e.message); } } });
  } else if (deletable) {
    actions.push({ label: "Delete", destructive: true, onclick: async () => { try { await API.del(r.id, false); await loadRequests(); } catch (e) { if (e.status !== 409) toast(e.message); await loadRequests(); } } });
  }
  actions.push({ label: "Cancel", onclick: () => {} });
  actionSheet(r.artist + " — " + r.title, actions);
}
function confirmPurge(r) {
  actionSheet("Delete “" + r.title + "” from your library? Removes the file from disk, takes it out of Plex and any playlists, and clears this entry.", [
    { label: "Delete File from Disk & Plex", destructive: true, onclick: async () => { try { await API.del(r.id, true); toast("Deleted"); await loadRequests(); } catch (e) { toast(e.message); } } },
    { label: "Cancel", onclick: () => {} },
  ]);
}
async function loadRequests() {
  try {
    const resp = await API.requests();
    reqData = resp.requests; if (typeof resp.now === "number") clockOffset = resp.now - Date.now() / 1000;
    reqLoadErr = null; reqLoaded = true;
  } catch (e) { reqLoadErr = e.message; reqLoaded = true; }
  if (currentTab === "requests") { renderRequests(); }
}
async function checkStatus(force) {
  if (!force && Date.now() - lastStatusAt < 30000) return;
  lastStatusAt = Date.now();
  try { cachedStatus = await API.status(); } catch {}
  if (currentTab === "requests") renderRequestsBody();
}

// ---------- Settings view ----------
let cfg = {};
let _extrasWrap = null;
function renderSettings() {
  const v = $("#view-settings"); v.innerHTML = "";
  v.append(h("div", { class: "nav" }, h("div", { class: "nav-row" }, h("h1", {}, "Settings"))));
  const body = h("div");

  // Server section
  const urlIn = h("input", { class: "v", type: "url", value: baseURL, placeholder: "https://…", autocapitalize: "off", inputmode: "url" });
  const keyIn = h("input", { class: "v", type: "password", value: apiKey, placeholder: "API key" });
  const serverStatusRow = h("div");
  body.append(h("div", { class: "section-hdr" }, "Songdrop Server"),
    h("div", { class: "group" },
      h("div", { class: "srow full" }, urlIn),
      h("div", { class: "srow full" }, keyIn),
      h("button", { class: "cellbtn", id: "test-conn", onclick: async () => {
        baseURL = urlIn.value.trim(); apiKey = keyIn.value.trim();
        LS.setItem("ts_url", baseURL); LS.setItem("ts_key", apiKey);
        const btn = $("#test-conn"); btn.innerHTML = ""; btn.append(h("div", { class: "spinner" }));
        await testConnection(serverStatusRow);
        btn.textContent = "Test Connection";
      } }, "Test Connection"),
      serverStatusRow),
    h("div", { class: "section-ftr" }, "The base URL of your Songdrop server. Use HTTPS or a VPN (Tailscale/WireGuard) to reach it away from home."));

  // slskd + Plex sections (loaded from /api/config)
  const slskdWrap = h("div"), plexWrap = h("div");
  body.append(slskdWrap, plexWrap);
  renderConfigSections(slskdWrap, plexWrap);

  // Sources (YouTube fallback toggle) + Storage (read-only paths); filled after connect
  _extrasWrap = h("div");
  body.append(_extrasWrap);

  // Defaults
  const plIn = h("input", { class: "v", value: defaultPlaylist, placeholder: "Default playlist (optional)", autocapitalize: "words",
    onchange: (e) => { defaultPlaylist = e.target.value.trim(); LS.setItem("ts_playlist", defaultPlaylist); } });
  body.append(h("div", { class: "section-hdr" }, "Defaults"),
    h("div", { class: "group" }, h("div", { class: "srow full" }, plIn)),
    h("div", { class: "section-ftr" }, "Pre-selected when adding a song. Updated automatically to the last playlist you used."),
    h("div", { class: "spacer" }));

  v.append(body);
  if (baseURL && apiKey) testConnection(serverStatusRow);
}
async function testConnection(statusRow) {
  statusRow.innerHTML = "";
  try {
    cfg = await API.getConfig();
    statusRow.append(statusLine("Songdrop server", true, "connected"));
    populateConfigFields();
    cachedStatus = await API.status().catch(() => null);
    if (cachedStatus) {
      statusRow.append(statusLine("slskd", cachedStatus.slskd.ok, cachedStatus.slskd.detail));
      statusRow.append(statusLine("Plex", cachedStatus.plex.ok, cachedStatus.plex.detail));
    }
    renderExtras();
  } catch (e) {
    statusRow.append(statusLine("Songdrop server", false, e.status === 401 ? "Wrong API key" : e.message));
  }
}
function statusLine(name, ok, detail) {
  return h("div", { class: "srow" }, h("span", { class: "dot " + (ok ? "ok" : "bad") }), h("span", {}, name),
    h("span", { class: "status-detail" }, detail || ""));
}
function renderExtras() {
  if (!_extrasWrap) return;
  _extrasWrap.innerHTML = "";
  // Sources — YouTube fallback toggle (runtime config)
  const toggle = h("input", { type: "checkbox", style: "width:20px;height:20px;accent-color:var(--tint)" });
  toggle.checked = cfg.ytdlp_enabled !== false;
  toggle.addEventListener("change", async () => {
    const next = toggle.checked;
    try { await API.saveConfig({ ytdlp_enabled: next }); cfg.ytdlp_enabled = next; toast("YouTube fallback " + (next ? "on" : "off")); }
    catch (e) { toggle.checked = !next; toast(e.message); }
  });
  _extrasWrap.append(
    h("div", { class: "section-hdr" }, "Sources"),
    h("div", { class: "group" },
      h("label", { class: "srow", style: "cursor:pointer" }, h("span", {}, "YouTube fallback"),
        h("span", { style: "margin-left:auto;display:flex" }, toggle))),
    h("div", { class: "section-ftr" }, "When a track isn't on Soulseek, fall back to YouTube (yt-dlp, ~128 kbps). Off = Soulseek only; unfound tracks keep retrying."));
  // Storage — read-only server paths
  const p = cachedStatus && cachedStatus.paths;
  if (p) {
    _extrasWrap.append(
      h("div", { class: "section-hdr" }, "Storage (server paths)"),
      h("div", { class: "group" },
        pathRow("Downloads", p.slskd_downloads_dir),
        pathRow("Library", p.music_library_dir),
        pathRow("Plex reads", p.plex_library_dir)),
      h("div", { class: "section-ftr" }, "Where the server reads and writes, set by the container's volume mounts. If “Library” isn't the same folder your Plex music library points at, tracks won't show up in Plex."));
  }
}
function pathRow(k, v) {
  return h("div", { class: "srow" }, h("span", {}, k),
    h("span", { class: "status-detail", style: "font-family:ui-monospace,Menlo,monospace;font-size:12px;max-width:62%" }, v || "—"));
}
let cfgFields = {};
function renderConfigSections(slskdWrap, plexWrap) {
  cfgFields.slskdUrl = h("input", { class: "v", placeholder: "http://slskd:5030", autocapitalize: "off", inputmode: "url" });
  cfgFields.slskdUser = h("input", { class: "v", placeholder: "Username", autocapitalize: "off" });
  cfgFields.slskdPass = h("input", { class: "v", type: "password", placeholder: "Password" });
  cfgFields.slskdKey = h("input", { class: "v", type: "password", placeholder: "API key (optional)" });
  const slskdStatus = h("div");
  slskdWrap.innerHTML = "";
  slskdWrap.append(h("div", { class: "section-hdr" }, "slskd (Soulseek)"),
    h("div", { class: "group" },
      h("div", { class: "srow full" }, cfgFields.slskdUrl),
      h("div", { class: "srow full" }, cfgFields.slskdUser),
      h("div", { class: "srow full" }, cfgFields.slskdPass),
      h("div", { class: "srow full" }, cfgFields.slskdKey),
      h("button", { class: "cellbtn", id: "save-slskd", onclick: () => saveSection("slskd", slskdStatus) }, "Save & Test slskd"),
      slskdStatus),
    h("div", { class: "section-ftr" }, "Where downloads come from. The address is from the server's point of view."));

  cfgFields.plexUrl = h("input", { class: "v", placeholder: "http://plex:32400", autocapitalize: "off", inputmode: "url" });
  cfgFields.plexToken = h("input", { class: "v", type: "password", placeholder: "Plex token" });
  cfgFields.plexSection = h("input", { class: "v", placeholder: "Library section (optional)", autocapitalize: "words" });
  const plexStatus = h("div");
  plexWrap.innerHTML = "";
  plexWrap.append(h("div", { class: "section-hdr" }, "Plex"),
    h("div", { class: "group" },
      h("div", { class: "srow full" }, cfgFields.plexUrl),
      h("div", { class: "srow full" }, cfgFields.plexToken),
      h("div", { class: "srow full" }, cfgFields.plexSection),
      h("button", { class: "cellbtn", id: "save-plex", onclick: () => saveSection("plex", plexStatus) }, "Save & Test Plex"),
      plexStatus),
    h("div", { class: "section-ftr" }, "Used to scan new tracks into your library and manage playlists. Leave the section empty to auto-detect."));
}
function populateConfigFields() {
  if (!cfg || !cfgFields.slskdUrl) return;
  cfgFields.slskdUrl.value = cfg.slskd_url || "";
  cfgFields.slskdUser.value = cfg.slskd_username || "";
  cfgFields.slskdPass.value = cfg.slskd_password || "";
  cfgFields.slskdKey.value = cfg.slskd_api_key || "";
  cfgFields.plexUrl.value = cfg.plex_url || "";
  cfgFields.plexToken.value = cfg.plex_token || "";
  cfgFields.plexSection.value = cfg.plex_section || "";
}
async function saveSection(which, statusRow) {
  const btnId = which === "slskd" ? "#save-slskd" : "#save-plex";
  const btn = $(btnId); const label = btn.textContent; btn.innerHTML = ""; btn.append(h("div", { class: "spinner" }));
  const payload = which === "slskd"
    ? { slskd_url: cfgFields.slskdUrl.value.trim(), slskd_username: cfgFields.slskdUser.value.trim(), slskd_password: cfgFields.slskdPass.value, slskd_api_key: cfgFields.slskdKey.value.trim() }
    : { plex_url: cfgFields.plexUrl.value.trim(), plex_token: cfgFields.plexToken.value.trim(), plex_section: cfgFields.plexSection.value.trim() };
  statusRow.innerHTML = "";
  try { await API.saveConfig(payload); }
  catch (e) { statusRow.append(h("div", { class: "err" }, e.message)); btn.textContent = label; return; }
  btn.textContent = label;
  cachedStatus = await API.status().catch(() => null);
  if (cachedStatus) {
    const s = which === "slskd" ? cachedStatus.slskd : cachedStatus.plex;
    statusRow.append(statusLine(which === "slskd" ? "slskd" : "Plex", s.ok, s.detail));
  }
}

// ---------- tabs / router ----------
function goTab(name) {
  currentTab = name;
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  $("#view-" + name).classList.add("active");
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  window.scrollTo(0, 0);
  if (name === "search") renderSearch();
  if (name === "requests") { renderRequests(); loadRequests(); checkStatus(true); }
  if (name === "settings") renderSettings();
  manageTimers();
}
function manageTimers() {
  clearInterval(reqTimer); clearInterval(statusTimer);
  if (currentTab === "requests") {
    reqTimer = setInterval(loadRequests, 4000);
    statusTimer = setInterval(() => checkStatus(false), 10000);
  }
}

// ---------- onboarding ----------
function showOnboard() {
  $("#onboard").classList.add("show"); $("#app").classList.add("hidden");
  $("#ob-url").value = baseURL || window.location.origin;
  $("#ob-key").value = apiKey || "";
}
function hideOnboard() { $("#onboard").classList.remove("show"); $("#app").classList.remove("hidden"); }
async function connect() {
  const err = $("#ob-err"); err.classList.add("hidden");
  const btn = $("#ob-connect"); btn.innerHTML = ""; btn.append(h("div", { class: "spinner" }));
  baseURL = $("#ob-url").value.trim(); apiKey = $("#ob-key").value.trim();
  try {
    await API.getConfig();          // requires the key, so a wrong key fails here
    LS.setItem("ts_url", baseURL); LS.setItem("ts_key", apiKey);
    hideOnboard(); goTab("search");
  } catch (e) {
    err.textContent = e.status === 401 ? "That access key was rejected. Check it and try again." : e.message;
    err.classList.remove("hidden");
  } finally { btn.textContent = "Connect"; }
}

// ---------- boot ----------
function boot() {
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => goTab(t.dataset.tab)));
  $("#ob-connect").addEventListener("click", connect);
  tickTimer = setInterval(tickCountdowns, 1000);
  if (!baseURL || !apiKey) showOnboard(); else { hideOnboard(); goTab("search"); }
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
}
boot();
