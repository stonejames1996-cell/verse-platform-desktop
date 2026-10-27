/* Verse Platform desktop: clip library + settings. Talks to the app through window.pywebview.api */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
let api = null;
let S = {};               // last state from Python
let settings = {};
let clips = [];
let selecting = false;      // select mode for deleting several clips
const selected = new Set();
let lastPicked = null;      // for shift-click ranges
let order = [];             // clip ids in the order they're shown
let matches = {};           // League match details by id
const openMatches = new Set();
const closedMatches = new Set();
let ddVersion = "";         // League icon version from Riot's Data Dragon
let clipsRev = -1;
let filter = "All";
let openClipId = null;
let view = "clips";

const LENGTHS = [[15, "15s"], [30, "30s"], [60, "1m"], [90, "90s"], [120, "2m"], [180, "3m"], [300, "5m"]];
const SEG = 2;            // seconds per recorded chunk

// ---------------------------------------------------------------- helpers
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}
function icon(id) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", "#" + id);
  s.append(u);
  return s;
}
function fmtDur(sec) {
  sec = Math.round(sec || 0);
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}
function fmtBytes(b) {
  if (!b) return "0 MB";
  const gb = b / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(gb >= 10 ? 0 : 1)} GB` : `${Math.max(1, Math.round(b / 1024 ** 2))} MB`;
}
function fmtWhen(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  const t = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `Today, ${t}`;
  if (d.toDateString() === y.toDateString()) return `Yesterday, ${t}`;
  return d.toLocaleDateString([], { day: "numeric", month: "short" }) + `, ${t}`;
}
function fmtLen(sec) {
  return sec % 60 === 0 ? `${sec / 60} min` : `${sec} seconds`;
}
let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3200);
}
async function call(name, ...args) {
  try {
    return await api[name](...args);
  } catch (e) {
    console.error(name, e);
    toast("Something went wrong. Details are in the log.");
    return null;
  }
}

// ---------------------------------------------------------------- navigation
function show(v) {
  view = v;
  for (const b of $$(".rail-btn")) {
    if (b.dataset.view === v) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  for (const s of $$(".view")) s.hidden = s.id !== "view-" + v;
  if (v === "settings") loadSettings();
  if (v !== "clips" && selecting) setSelecting(false);
}

// ---------------------------------------------------------------- deck (live status + tape)
function buildTape(seconds) {
  const tape = $("#tape");
  const n = Math.max(8, Math.min(60, Math.ceil(seconds / SEG)));
  if (tape.children.length !== n) {
    tape.replaceChildren(...Array.from({ length: n }, () => el("i")));
  }
  return [...tape.children];
}
function renderDeck() {
  const deck = $("#deck");
  deck.classList.toggle("recording", !!S.capturing);
  $("#deck-title").textContent = S.title || "Verse Platform";
  $("#deck-sub").textContent = S.subtitle || "";
  const hk = (S.hotkey || "alt+f10").toUpperCase().replace(/\+/g, " + ");
  $("#deck-hotkey").textContent = hk;
  for (const k of $$("[data-hotkey]")) k.textContent = hk;
  const ticks = buildTape(S.buffer_seconds || 60);
  const filled = Math.min(ticks.length, Math.round(((S.buffered_seconds || 0) / (S.buffer_seconds || 60)) * ticks.length));
  ticks.forEach((t, i) => {
    t.className = i < filled ? (S.capturing && i === filled - 1 ? "on head" : "on") : "";
  });
  const ub = $("#update-btn");
  ub.hidden = !S.update;
  if (S.update) $("#update-ver").textContent = S.update;
  $("#tape").setAttribute("aria-label", `${Math.round(S.buffered_seconds || 0)} of ${S.buffer_seconds} seconds ready to save`);
}

// ---------------------------------------------------------------- clips
function isPosted(c) {
  return !!(c.posted && c.posted.at);
}

async function loadClips() {
  const [r, m] = await Promise.all([call("list_clips"), call("list_matches")]);
  if (!r) return;
  clips = r;
  matches = Object.fromEntries((m || []).map((x) => [x.id, x]));
  if (!ddVersion && Object.keys(matches).length) loadDD();
  renderClips();
  if (openClipId) renderPlayerBar();
}
function renderClips() {
  const games = [...new Set(clips.map((c) => c.game || "Other"))];
  if (filter !== "All" && !games.includes(filter)) filter = "All";
  $("#filters").replaceChildren(
    ...(games.length > 1 ? ["All", ...games] : []).map((g) =>
      el("button", { role: "tab", "aria-selected": String(g === filter), onclick: () => { filter = g; renderClips(); } }, g)
    )
  );
  const shown = clips.filter((c) => filter === "All" || (c.game || "Other") === filter);
  order = [];
  document.body.classList.toggle("selecting", selecting);
  $("#clips-empty").hidden = clips.length > 0;
  const groups = new Map();
  for (const c of shown) {
    const g = c.game || "Other";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(c);
  }
  $("#clip-groups").replaceChildren(
    ...[...groups].map(([g, list]) => {
      // clips from a League match go into that match's folder card
      const byMatch = new Map(), loose = [];
      for (const c of list) {
        if (c.match && matches[c.match]) {
          if (!byMatch.has(c.match)) byMatch.set(c.match, []);
          byMatch.get(c.match).push(c);
        } else loose.push(c);
      }
      const mOrder = [...byMatch.keys()].sort((a, b) => (matches[b].started || "").localeCompare(matches[a].started || ""));
      for (const id of mOrder) byMatch.get(id).sort((a, b) => (a.created || "").localeCompare(b.created || ""));
      for (const id of mOrder) order.push(...byMatch.get(id).map((c) => c.id));
      order.push(...loose.map((c) => c.id));
      const n = byMatch.size;
      const ids = list.map((c) => c.id);
      return el("section", { class: "group" },
        el("div", { class: "group-head" }, el("h3", {}, g),
          el("span", {}, (n ? `${n} game${n > 1 ? "s" : ""} · ` : "") + `${list.length} clip${list.length > 1 ? "s" : ""}`),
          selecting ? el("button", { class: "link-btn", onclick: () => selectMany(ids) },
            ids.every((i) => selected.has(i)) ? "Unselect all" : `Select all ${list.length}`) : null),
        ...mOrder.map((id, i) => matchCard(matches[id], byMatch.get(id), i === 0)),
        loose.length && n ? el("div", { class: "loose-head" }, "Other clips") : null,
        loose.length ? el("div", { class: "grid" }, loose.map(clipCard)) : null
      );
    })
  );
}

function loadDD() {
  ddVersion = "pending";
  fetch("https://ddragon.leagueoflegends.com/api/versions.json").then((r) => r.json())
    .then((v) => { ddVersion = v[0]; renderClips(); }).catch(() => { ddVersion = ""; });
}
function fmtLen(sec) {
  return sec ? `${Math.max(1, Math.round(sec / 60))} min` : "";
}
function matchCard(m, list, latest) {
  const open = openMatches.has(m.id) || (latest && !closedMatches.has(m.id));
  const deaths = list.filter((c) => c.review), plays = list.filter((c) => !c.review);
  const icon = el("span", { class: "m-champ" }, (m.champion || "?")[0]);
  if (m.icon_url) {
    const img = el("img", { src: m.icon_url, alt: "" });
    img.onerror = () => img.remove();
    icon.append(img);
  } else if (m.champion_key && ddVersion && ddVersion !== "pending") {
    const img = el("img", { src: `https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${m.champion_key}.png`, alt: "" });
    img.onerror = () => img.remove();
    icon.append(img);
  }
  const meta = [];
  if (m.result) meta.push(el("b", { class: m.result === "Win" ? "win" : "loss" }, m.result));
  if (m.kills != null) meta.push(`${m.kills} / ${m.deaths} / ${m.assists}`);
  if (m.length) meta.push(fmtLen(m.length));
  if (m.started) meta.push(fmtWhen(m.started));
  const metaEl = el("span", { class: "m-meta" });
  meta.forEach((x, i) => { if (i) metaEl.append(" · "); metaEl.append(x); });
  const head = el("button", { class: "m-head", "aria-expanded": String(open), onclick: () => {
      if (open) { openMatches.delete(m.id); closedMatches.add(m.id); }
      else { closedMatches.delete(m.id); openMatches.add(m.id); }
      renderClips();
    } },
    icon,
    el("span", { class: "m-title" },
      el("strong", {}, m.mode || "Match", el("i", {}, m.joiner || " as "), m.champion || ""),
      metaEl),
    el("span", { class: "m-count" }, `${plays.length} clip${plays.length !== 1 ? "s" : ""}` + (deaths.length ? ` · ${deaths.length} death${deaths.length > 1 ? "s" : ""}` : "")),
    open ? null : el("span", { class: "m-thumbs" }, plays.slice(0, 4).map((c) =>
      c.thumb_url ? el("img", { src: c.thumb_url, alt: "", loading: "lazy" }) : el("span"))),
    el("span", { class: "m-chev", "aria-hidden": "true" })
  );
  const ids = list.map((c) => c.id);
  const all = ids.every((i) => selected.has(i));
  const pick = selecting ? el("button", { class: "m-sel" + (all ? " on" : ""), "aria-pressed": String(all),
    title: all ? "Unselect this game's clips" : "Select this game's clips", onclick: () => selectMany(ids) },
    el("span", { class: "tick" }), all ? "Selected" : "Select game") : null;
  return el("div", { class: "match" + (open ? " open" : "") + (all && selecting ? " picked" : "") },
    el("div", { class: "m-top" }, head, pick),
    open && m.summary ? matchSummary(m.summary, plays) : null,
    open && plays.length ? el("div", { class: "grid m-grid" }, plays.map(clipCard)) : null,
    open && deaths.length ? el("details", { class: "m-deaths" },
      el("summary", {}, `Death review · ${deaths.length}`, el("small", {}, " only on this PC, never posted unless you choose to")),
      el("div", { class: "grid m-grid" }, deaths.map(clipCard))) : null);
}
// the best auto clip of a game: the rarest moment wins
const CLIP_RANK = ["penta", "steal", "quadra", "ace", "elder", "baron", "triple", "teamfight", "double", "first blood", "victory", "dragon", "kill"];
function bestClip(plays) {
  const rank = (c) => {
    const t = (c.title || "").toLowerCase();
    const i = CLIP_RANK.findIndex((k) => t.includes(k));
    return c.highlight ? (i < 0 ? CLIP_RANK.length : i) : CLIP_RANK.length + 1;
  };
  return [...plays].filter((c) => !isPosted(c)).sort((a, b) => rank(a) - rank(b))[0];
}
// end of game numbers for a League match, vs the player's own average from past games
function matchSummary(s, plays) {
  const avg = s.avg || {};
  const stat = (value, label, now, base, fmt) => {
    let vs = "", cls = "";
    if (base != null && now != null) {
      const up = now > base * 1.04, down = now < base * 0.96;
      vs = `avg ${fmt(base)}` + (up ? " \u25b2" : down ? " \u25bc" : "");
      cls = up ? "up" : down ? "down" : "";
    }
    return el("div", { class: "ms-stat" }, el("strong", {}, value), el("span", {}, label), vs ? el("small", { class: cls }, vs) : null);
  };
  const best = bestClip(plays);
  return el("div", { class: "m-summary" },
    stat(`${s.kills}/${s.deaths}/${s.assists}`, "K / D / A"),
    stat((s.cs_min || 0).toFixed(1), `CS per min (${s.cs} CS)`, s.cs_min, avg.cs_min, (v) => v.toFixed(1)),
    s.kp != null ? stat(`${Math.round(s.kp * 100)}%`, "Kill share", s.kp, avg.kp, (v) => `${Math.round(v * 100)}%`) : null,
    stat((s.vision_min || 0).toFixed(2), `Vision per min (${Math.round(s.vision || 0)})`, s.vision_min, avg.vision_min, (v) => v.toFixed(2)),
    best ? el("button", { class: "btn btn-primary ms-post", onclick: () => openPlayer(best.id) }, `Post ${best.title}`) : null);
}
function clipCard(c) {
  const posted = isPosted(c);
  const on = selected.has(c.id);
  return el("div", { class: "clip-wrap" + (on ? " sel" : "") },
    el("button", { class: "clip", onclick: (e) => (selecting ? pickClip(c.id, e.shiftKey) : openPlayer(c.id)),
        "aria-label": `${c.title}, ${fmtDur(c.duration)}`, "aria-pressed": selecting ? String(on) : null },
      el("div", { class: "clip-thumb" },
        c.thumb_url ? el("img", { src: c.thumb_url, alt: "", loading: "lazy" }) : null,
        posted ? el("span", { class: "up uploaded" }, icon("i-check"), "Posted") : null,
        c.highlight && !posted && !c.review && !c.squad ? el("span", { class: "up auto" }, "Auto") : null,
      c.recap ? el("span", { class: "up auto" }, "Recap") : null,
      c.vertical ? el("span", { class: "up auto" }, "9:16") : null,
      c.squad_combo ? el("span", { class: "up squad" }, "Squad POV") : c.squad ? el("span", { class: "up squad" }, "Squad") : null,
        el("span", { class: "dur" }, fmtDur(c.duration))
      ),
      el("div", { class: "clip-name" }, c.title),
      el("div", { class: "clip-when" }, c.match ? (c.highlight ? "Auto clip" : "Saved with your shortcut") : fmtWhen(c.created))
    ),
    el("button", { class: "c-check", "aria-label": on ? `Unselect ${c.title}` : `Select ${c.title}`, title: "Select",
      onclick: (e) => pickClip(c.id, e.shiftKey) }, el("span", { class: "tick" })),
    selecting ? null : el("button", { class: "c-del", "aria-label": `Delete ${c.title}`, title: "Delete",
      onclick: () => confirmDelete([c.id]) }, icon("i-trash")),
    selecting ? null : el("button", { class: "c-star" + (c.starred ? " on" : ""), "aria-pressed": String(!!c.starred),
      "aria-label": c.starred ? `Unstar ${c.title}` : `Star ${c.title}`, title: c.starred ? "Starred: never cleaned up" : "Star",
      onclick: async () => { await call("set_star", c.id, !c.starred); loadClips(); } }, icon("i-star"))
  );
}

// ---------------------------------------------------------------- selecting and deleting
function setSelecting(on) {
  selecting = on;
  if (!on) { selected.clear(); lastPicked = null; }
  renderSelectBar();
  renderClips();
}
function renderSelectBar() {
  $("#select-bar").hidden = !selecting;
  $("#select-btn").classList.toggle("on", selecting);
  $("#select-count").textContent = selected.size ? `${selected.size} selected` : "Pick clips to delete";
  $("#select-delete").disabled = !selected.size;
  const all = order.length && order.every((i) => selected.has(i));
  $("#select-all").textContent = all ? "Unselect all" : "Select all";
}
function pickClip(id, range) {
  if (!selecting) selecting = true;
  if (range && lastPicked && order.includes(lastPicked)) {
    const a = order.indexOf(lastPicked), b = order.indexOf(id);
    for (const i of order.slice(Math.min(a, b), Math.max(a, b) + 1)) selected.add(i);
  } else if (selected.has(id)) selected.delete(id);
  else selected.add(id);
  lastPicked = id;
  renderSelectBar();
  renderClips();
}
function selectMany(ids) {
  selecting = true;
  const all = ids.every((i) => selected.has(i));
  for (const i of ids) all ? selected.delete(i) : selected.add(i);
  renderSelectBar();
  renderClips();
}
function askConfirm(title, text, yes) {
  return new Promise((resolve) => {
    const box = $("#confirm");
    $("#confirm-title").textContent = title;
    $("#confirm-text").textContent = text;
    $("#confirm-yes").lastChild.textContent = yes;
    box.hidden = false;
    const done = (v) => { box.hidden = true; box.onclick = null; window.removeEventListener("keydown", key, true); resolve(v); };
    const key = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); done(false); }
      if (e.key === "Enter") { e.stopPropagation(); e.preventDefault(); done(true); }
    };
    window.addEventListener("keydown", key, true);
    $("#confirm-yes").onclick = () => done(true);
    $("#confirm-no").onclick = () => done(false);
    box.onclick = (e) => { if (e.target === box) done(false); };
    $("#confirm-yes").focus();
  });
}
async function confirmDelete(ids) {
  ids = ids.filter((i) => clips.some((c) => c.id === i));
  if (!ids.length) return;
  const list = clips.filter((c) => ids.includes(c.id));
  const n = ids.length;
  const posted = list.filter(isPosted).length;
  const title = n === 1 ? `Delete "${list[0].title}"?` : `Delete ${n} clips?`;
  let text = `${n === 1 ? "It goes" : "They go"} to your Recycle Bin, so you can get ${n === 1 ? "it" : "them"} back from there if you change your mind.`;
  if (posted) text += ` ${posted === n ? (n === 1 ? "It's" : "They're") : `${posted} of them ${posted === 1 ? "is" : "are"}`} already posted on Verse and will stay there.`;
  if (!(await askConfirm(title, text, n === 1 ? "Delete" : `Delete ${n} clips`))) return;
  if (openClipId && ids.includes(openClipId)) closePlayer();
  const r = await call("delete_clips", ids);
  if (r) {
    let msg = r.deleted === 1 ? "Clip moved to the Recycle Bin" : `${r.deleted} clips moved to the Recycle Bin`;
    if (r.failed) msg += `. ${r.failed} couldn't be deleted because ${r.failed === 1 ? "it's" : "they're"} open in another app`;
    toast(msg);
  }
  for (const i of ids) selected.delete(i);
  if (selecting) setSelecting(false);
  await loadClips();
}

// ---------------------------------------------------------------- preview, trim, publish
let trim = { start: 0, end: 0, dur: 0 };
const MAX_POST = () => S.max_post_seconds || 60;

function openPlayer(id) {
  const c = clips.find((x) => x.id === id);
  if (!c) return;
  openClipId = id;
  $("#player-title").value = c.title;
  const v = $("#player-video");
  v.src = c.video_url;
  $("#player").hidden = false;
  setupTrim(c.duration || 0);
  v.addEventListener("loadedmetadata", () => {
    if (isFinite(v.duration) && Math.abs(v.duration - trim.dur) > 0.5) setupTrim(v.duration);
  }, { once: true });
  v.play().catch(() => {});
  renderPlayerBar();
  $("#player-star").setAttribute("aria-pressed", String(!!c.starred));
  $("#remove-voice").checked = false;
  $("#voice-row").hidden = true;
  call("clip_tracks", id).then((n) => { if (openClipId === id) $("#voice-row").hidden = !(n >= 2); });
}
function setupTrim(dur) {
  trim.dur = Math.max(1, dur);
  trim.end = trim.dur;
  trim.start = Math.max(0, trim.dur - MAX_POST()); // default: the last 60 seconds, where the play is
  for (const r of [$("#trim-start"), $("#trim-end")]) r.max = trim.dur.toFixed(1);
  $("#trim-start").value = trim.start;
  $("#trim-end").value = trim.end;
  renderTrim();
}
function renderTrim() {
  const pct = (x) => (x / trim.dur) * 100;
  $("#trim-fill").style.left = pct(trim.start) + "%";
  $("#trim-fill").style.width = pct(trim.end - trim.start) + "%";
  const len = trim.end - trim.start;
  $("#trim-label").textContent = `${fmtDur(trim.start)} to ${fmtDur(trim.end)}  ·  ${len.toFixed(1)}s`;
  $("#trim-hint").textContent = trim.dur <= MAX_POST()
    ? "The whole clip fits. Drag the ends to post just part of it."
    : `This clip is ${fmtDur(trim.dur)} long. Verse posts can be up to ${MAX_POST()} seconds, so pick the best part.`;
}
function onTrimInput(which) {
  const s = $("#trim-start"), e = $("#trim-end");
  let a = Number(s.value), b = Number(e.value);
  if (which === "start") {
    if (a > b - 1) a = b - 1;
    if (b - a > MAX_POST()) b = a + MAX_POST();
  } else {
    if (b < a + 1) b = a + 1;
    if (b - a > MAX_POST()) a = b - MAX_POST();
  }
  trim.start = Math.max(0, a);
  trim.end = Math.min(trim.dur, b);
  s.value = trim.start;
  e.value = trim.end;
  const v = $("#player-video");
  v.currentTime = which === "start" ? trim.start : Math.max(trim.start, trim.end - 1);
  renderTrim();
}
let stopAt = null;
function playSelection() {
  const v = $("#player-video");
  v.currentTime = trim.start;
  stopAt = trim.end;
  v.play().catch(() => {});
}
function renderPlayerBar() {
  const c = clips.find((x) => x.id === openClipId);
  if (!c) return closePlayer();
  $("#player-meta").replaceChildren(el("span", {}, c.game || "Clip"), el("span", {}, fmtDur(c.duration)),
    el("span", {}, `${(c.size / 1048576).toFixed(0)} MB`), el("span", {}, fmtWhen(c.created)));
  $("#player-posted").hidden = !isPosted(c);
  $("#publish-btn").lastChild.textContent = isPosted(c) ? "Publish again" : "Publish to Verse";
}
function closePlayer() {
  const v = $("#player-video");
  v.pause();
  v.removeAttribute("src");
  v.load();
  $("#player").hidden = true;
  openClipId = null;
  stopAt = null;
}
async function publish() {
  const btn = $("#publish-btn");
  if (btn.disabled) return;
  btn.disabled = true;
  const label = btn.lastChild.textContent;
  btn.lastChild.textContent = "Preparing...";
  $("#player-video").pause();
  const r = await call("publish_clip", openClipId, trim.start, trim.end, $("#remove-voice").checked);
  btn.disabled = false;
  btn.lastChild.textContent = label;
  if (!r) return;
  if (r.error) return toast(r.error);
  toast("Opening Verse to post your clip...");
}

// ---------------------------------------------------------------- settings
async function loadSettings() {
  const r = await call("get_settings");
  if (!r) return;
  settings = r;
  // clip length buttons
  $("#len-seg").replaceChildren(...LENGTHS.map(([sec, label]) =>
    el("button", { role: "radio", "data-set": "buffer_seconds", "data-value": sec, "data-num": true, title: fmtLen(sec) }, label)));
  // mic list
  const mic = $("#mic-select");
  mic.replaceChildren(el("option", { value: "" }, "No microphone"), ...r.mics.map((m) => el("option", { value: m }, m)));
  // keep a hand-edited quality value selectable
  const q = $("select[data-set=bitrate]");
  $$("option[data-custom]", q).forEach((o) => o.remove());
  if (![...q.options].some((o) => o.value === r.config.bitrate)) {
    q.append(el("option", { value: r.config.bitrate, "data-custom": true }, `Custom (${r.config.bitrate}bps)`));
  }
  // simple bindings
  for (const b of $$("[data-set]")) {
    const key = b.dataset.set;
    const val = r.config[key];
    if (b.tagName === "BUTTON") b.setAttribute("aria-checked", String(String(val) === b.dataset.value));
    else if (b.type === "checkbox") b.checked = !!val;
    else b.value = String(val ?? "");
  }
  const hl = Object.assign({}, r.highlight_defaults || {}, r.config.highlight_events || {});
  for (const c of $$("[data-hl]")) c.checked = !!hl[c.dataset.hl];
  $("#hl-body").classList.toggle("off", !r.config.auto_highlights);
  const gs = r.gsi_games || {};
  const found = Object.entries(gs).filter(([, ok]) => ok).map(([g]) => g);
  $("#gsi-note").textContent = found.length
    ? `Set up for ${found.join(" and ")}.` + (gs["Dota 2"] ? " Dota 2 also needs -gamestateintegration in its Steam launch options." : "")
    : "";
  call("squad_status").then((sq) => {
    if (!sq) return;
    $("#squad-status").textContent = !sq.code ? "Make a code and send it to your mates, or paste theirs"
      : sq.error ? sq.error
      : sq.connected ? `Connected as ${sq.name}` : `You're ${sq.name}. Works while you're in a game`;
    $("#squad-copy").hidden = !sq.code;
  });
  const combo = $("#combo-select");
  if (combo && r.controller_combos) {
    combo.replaceChildren(el("option", { value: "" }, "Off"),
      ...Object.entries(r.controller_combos).map(([k, v]) => el("option", { value: k }, v)));
    combo.value = r.config.controller_combo || "";
  }
  call("storage_info").then((st) => {
    if (!st) return;
    const pct = st.total ? Math.min(100, (st.used / st.total) * 100) : 0;
    $("#store-used").style.width = Math.max(pct, st.used ? 1 : 0) + "%";
    $("#store-text").textContent = `Your clips use ${fmtBytes(st.used)} (${st.count} clip${st.count === 1 ? "" : "s"}). ${fmtBytes(st.free)} free on this drive.`;
    $("#clean-row").hidden = !st.old_count;
    $("#clean-text").textContent = `${st.old_count} old clip${st.old_count === 1 ? "" : "s"} can go (${fmtBytes(st.old_bytes)})`;
  });
  $("#autostart").checked = r.autostart;
  $("#hotkey-btn").textContent = r.config.hotkey.toUpperCase().replace(/\+/g, " + ");
  $("#folder-path").textContent = r.config.clips_folder;
  $("#version").textContent = `Verse Platform for Windows ${r.version}. Updates install by themselves`;
  $("#known-games-hint").textContent = `${r.known_games.length} popular games are picked up automatically, including ${r.known_games.slice(0, 6).join(", ")}.`;
  renderCustomGames();
  const apps = $("#running-apps");
  apps.replaceChildren(el("option", { value: "" }, r.running_apps.length ? "Choose a running app" : "No other apps open"),
    ...r.running_apps.map((a) => el("option", { value: a.exe, "data-name": a.name }, `${a.name} (${a.exe})`)));
}
function renderCustomGames() {
  const games = settings.config.custom_games || {};
  $("#custom-games").replaceChildren(...Object.entries(games).map(([exe, name]) =>
    el("li", {}, `${name}`, el("button", { "aria-label": `Remove ${name}`, onclick: async () => {
      await call("remove_game", exe); loadSettings();
    } }, icon("i-close")))));
}
async function setSetting(key, value) {
  const r = await call("set_setting", key, value);
  if (r && r.message) toast(r.message);
  await loadSettings();
}
// hotkey capture
let listening = false;
function hotkeyFromEvent(e) {
  const k = e.key;
  if (["Control", "Shift", "Alt", "Meta"].includes(k)) return null;
  const parts = [];
  if (e.ctrlKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  if (e.shiftKey) parts.push("shift");
  let key = k.length === 1 ? k.toLowerCase() : k.toLowerCase();
  const map = { " ": "space", arrowup: "up", arrowdown: "down", arrowleft: "left", arrowright: "right", escape: "esc", pageup: "page up", pagedown: "page down" };
  key = map[key] || key;
  parts.push(key);
  return parts.join("+");
}

// ---------------------------------------------------------------- wiring
function wire() {
  for (const b of $$(".rail-btn")) b.addEventListener("click", () => show(b.dataset.view));
  $("#save-btn").addEventListener("click", async () => {
    const r = await call("save_clip");
    if (r && r.message) toast(r.message);
  });
  $("#open-folder").addEventListener("click", () => call("open_clips_folder"));

  document.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-set]");
    if (!b) return;
    setSetting(b.dataset.set, "num" in b.dataset ? Number(b.dataset.value) : b.dataset.value);
  });
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (!t.dataset || !t.dataset.set) return;
    const v = t.type === "checkbox" ? t.checked : "num" in t.dataset ? Number(t.value) : t.value;
    setSetting(t.dataset.set, v);
  });
  document.addEventListener("change", (e) => {
    const c = e.target;
    if (!c.dataset || !c.dataset.hl) return;
    const ev = Object.assign({}, settings.highlight_defaults || {}, settings.config.highlight_events || {});
    ev[c.dataset.hl] = c.checked;
    setSetting("highlight_events", ev);
  });
  $("#squad-new").addEventListener("click", async () => {
    const r = await call("squad_new_code");
    if (r && r.code) {
      try { await navigator.clipboard.writeText(r.code); toast(`Squad code ${r.code} copied. Send it to your mates`); }
      catch { toast(`Your squad code is ${r.code}`); }
    }
    loadSettings();
  });
  $("#squad-copy").addEventListener("click", async () => {
    const code = $("#squad-code").value;
    try { await navigator.clipboard.writeText(code); toast("Squad code copied"); } catch { toast(code); }
  });
  $("#autostart").addEventListener("change", (e) => call("set_autostart", e.target.checked));
  $("#check-updates").addEventListener("click", async (e) => {
    const b = e.currentTarget;
    b.disabled = true; b.textContent = "Checking...";
    const r = await call("check_updates");
    b.disabled = false; b.textContent = "Check for updates";
    if (r && r.message) toast(r.message);
    tick();
  });
  $("#change-folder").addEventListener("click", async () => {
    const r = await call("choose_clips_folder");
    if (r && r.message) toast(r.message);
    loadSettings();
  });
  $("#add-game").addEventListener("click", async () => {
    const sel = $("#running-apps");
    const opt = sel.selectedOptions[0];
    if (!sel.value) return toast("Open the game, then pick it from the list");
    await call("add_game", sel.value, opt.dataset.name);
    toast(`${opt.dataset.name} added`);
    loadSettings();
  });

  const hk = $("#hotkey-btn");
  hk.addEventListener("click", () => {
    listening = true;
    hk.classList.add("listening");
    hk.textContent = "Press keys...";
  });
  window.addEventListener("keydown", async (e) => {
    if (!listening) {
      if (e.key === "Escape" && openClipId) closePlayer();
      return;
    }
    e.preventDefault();
    if (e.key === "Escape") {
      listening = false;
      hk.classList.remove("listening");
      return loadSettings();
    }
    const combo = hotkeyFromEvent(e);
    if (!combo) return;
    listening = false;
    hk.classList.remove("listening");
    await setSetting("hotkey", combo);
  });

  $("#player-close").addEventListener("click", closePlayer);
  $("#player").addEventListener("click", (e) => { if (e.target.id === "player") closePlayer(); });
  $("#player-title").addEventListener("change", async (e) => {
    await call("rename_clip", openClipId, e.target.value);
    loadClips();
  });
  $("#player-title").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });
  $("#publish-btn").addEventListener("click", publish);
  $("#trim-start").addEventListener("input", () => onTrimInput("start"));
  $("#trim-end").addEventListener("input", () => onTrimInput("end"));
  $("#trim-play").addEventListener("click", playSelection);
  $("#player-video").addEventListener("timeupdate", (e) => {
    if (stopAt != null && e.target.currentTime >= stopAt) { e.target.pause(); stopAt = null; }
  });
  for (const id of ["#go-verse", "#go-verse-logo"]) $(id).addEventListener("click", () => call("go_verse", "/Home"));
  $("#player-folder").addEventListener("click", () => call("show_in_folder", openClipId));
  $("#player-delete").addEventListener("click", () => confirmDelete([openClipId]));
  $("#player-star").addEventListener("click", async () => {
    const on = $("#player-star").getAttribute("aria-pressed") !== "true";
    $("#player-star").setAttribute("aria-pressed", String(on));
    await call("set_star", openClipId, on);
    toast(on ? "Starred: this clip won't be cleaned up" : "Star removed");
    loadClips();
  });
  for (const b of $$("[data-vertical]")) b.addEventListener("click", async () => {
    if (b.disabled) return;
    const btns = $$("[data-vertical]");
    btns.forEach((x) => (x.disabled = true));
    const label = b.textContent;
    b.textContent = "Making...";
    $("#player-video").pause();
    const r = await call("export_vertical", openClipId, trim.start, trim.end, b.dataset.vertical, $("#remove-voice").checked);
    btns.forEach((x) => (x.disabled = false));
    b.textContent = label;
    if (!r) return;
    if (r.error) return toast(r.error);
    toast("Vertical clip saved to My clips");
    await loadClips();
    openPlayer(r.id);
  });
  $("#recap-btn").addEventListener("click", async () => {
    const p = await call("recap_preview");
    if (!p) return;
    if (p.count < 2) return toast("Not enough clips from the last week for a recap yet. Save a few more!");
    if (!(await askConfirm("Make your weekly recap?",
      `Stitches your ${p.count} best clips from the last 7 days into one ${p.seconds} second video, ready to post. It can take a minute.`,
      "Make recap"))) return;
    const b = $("#recap-btn");
    b.disabled = true;
    b.lastChild.textContent = "Making recap...";
    const r = await call("make_recap");
    b.disabled = false;
    b.lastChild.textContent = "Weekly recap";
    if (!r) return;
    if (r.error) return toast(r.error);
    toast(`${r.title} saved to My clips`);
    await loadClips();
    openPlayer(r.id);
  });
  $("#clean-now").addEventListener("click", async () => {
    const t = $("#clean-text").textContent;
    if (!(await askConfirm("Clean up now?", t + ". Starred and posted clips are kept.", "Clean up"))) return;
    const r = await call("clean_now");
    if (r && r.message) toast(r.message);
    loadClips();
    loadSettings();
  });
  $("#select-btn").addEventListener("click", () => setSelecting(!selecting));
  $("#select-cancel").addEventListener("click", () => setSelecting(false));
  $("#select-all").addEventListener("click", () => selectMany(order));
  $("#select-delete").addEventListener("click", () => confirmDelete([...selected]));
  window.addEventListener("keydown", (e) => {
    if (!$("#confirm").hidden || e.target.matches("input, textarea, select")) return;
    if (selecting) {
      if (e.key === "Escape") setSelecting(false);
      else if ((e.key === "Delete" || e.key === "Backspace") && selected.size) confirmDelete([...selected]);
      else if (e.key.toLowerCase() === "a" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); selectMany(order); }
    } else if (e.key === "Delete" && openClipId) confirmDelete([openClipId]);
  });
}

async function startUpdate() {
  const b = $("#update-btn");
  b.disabled = true;
  b.textContent = "Updating...";
  const r = await call("update_now");
  if (!r || !r.ok) { b.disabled = false; renderDeckUpdateLabel(); }
}
function renderDeckUpdateLabel() {
  $("#update-btn").innerHTML = 'Update to <span id="update-ver"></span>';
  $("#update-ver").textContent = S.update || "";
}

async function tick() {
  const r = await call("get_state");
  if (!r) return;
  S = r;
  renderDeck();
  if (r.clips_rev !== clipsRev) {
    clipsRev = r.clips_rev;
    await loadClips();
  }
  if (r.notice) toast(r.notice);
}

async function start() {
  api = window.pywebview.api;
  wire();
  $("#update-btn").addEventListener("click", startUpdate);
  show("clips");
  await tick();
  setInterval(tick, 1000);
}
if (window.pywebview && window.pywebview.api) start();
else window.addEventListener("pywebviewready", start, { once: true });
