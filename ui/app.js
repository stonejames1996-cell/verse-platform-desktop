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
// game logos for the filter tabs and headings (ui/games), or a letter badge for games without one
const GAME_LOGOS = new Set(["apex-legends", "counter-strike-2", "dead-by-daylight", "destiny-2", "dota-2", "escape-from-tarkov", "fortnite", "gta-v", "league-of-legends", "marvel-rivals", "minecraft", "old-school-runescape", "overwatch-2", "pubg", "rainbow-six-siege", "roblox", "rust", "valorant", "world-of-warcraft"]);
function gameLogo(name) {
  if (!name || name === "All") return null;
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  if (GAME_LOGOS.has(slug)) return el("img", { class: "g-logo", src: `games/${slug}.png`, alt: "" });
  const letters = name.split(/\s+/).filter((w) => /[A-Za-z0-9]/.test(w[0])).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return el("span", { class: "g-logo g-letter", "aria-hidden": "true" }, letters || "?");
}
function renderClips() {
  const games = [...new Set(clips.map((c) => c.game || "Other"))];
  if (filter !== "All" && !games.includes(filter)) filter = "All";
  $("#filters").replaceChildren(
    ...(games.length > 1 ? ["All", ...games] : []).map((g) =>
      el("button", { role: "tab", "aria-selected": String(g === filter), onclick: () => { filter = g; renderClips(); } }, gameLogo(g), g)
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
        el("div", { class: "group-head" }, el("h3", {}, gameLogo(g), g),
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
    open && m.summary && m.summary.analysis ? matchAnalysis(m.summary.analysis, m.summary.champion, m.id, m.summary.champion_key || m.champion_key) : null,
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
// the lobby's average rank with its rank icon (OP.GG's medal for that tier)
function lobbyStat(r) {
  const tier = (r.lobby || "").split(" ")[0].toLowerCase();
  const src = r.lobby_image || (tier ? `https://opgg-static.akamaized.net/images/medals_new/${tier}.png` : "");
  return el("div", { class: "ms-stat ms-rank" },
    src ? el("img", { src, alt: "", onerror: (e) => e.target.remove() }) : null,
    el("div", {}, el("strong", {}, r.lobby), el("span", {}, "Lobby's average rank")));
}
// end of game numbers for a League match, vs the player's own average from past games
function matchSummary(s, plays) {
  const avg = s.avg || {};
  const stat = (value, label, now, base, fmt) => {
    let vs = "", cls = "";
    if (base != null && now != null) {
      const up = now > base * 1.04, down = now < base * 0.96;
      vs = `avg ${fmt(base)}` + (up ? " \u25b2" : down ? " \u25bc" : "");
      cls = up ? "s-up" : down ? "s-down" : "";
    }
    return el("div", { class: "ms-stat" }, el("strong", {}, value), el("span", {}, label), vs ? el("small", { class: cls }, vs) : null);
  };
  const best = bestClip(plays);
  return el("div", { class: "m-summary" },
    stat(`${s.kills}/${s.deaths}/${s.assists}`, "K / D / A"),
    stat((s.cs_min || 0).toFixed(1), `CS per min (${s.cs} CS)`, s.cs_min, avg.cs_min, (v) => v.toFixed(1)),
    s.kp != null ? stat(`${Math.round(s.kp * 100)}%`, "Kill share", s.kp, avg.kp, (v) => `${Math.round(v * 100)}%`) : null,
    stat((s.vision_min || 0).toFixed(2), `Vision per min (${Math.round(s.vision || 0)})`, s.vision_min, avg.vision_min, (v) => v.toFixed(2)),
    s.real && s.real.damage != null ? stat(Number(s.real.damage).toLocaleString(), `Damage to champions (${Math.round(s.real.dpm || 0)} a min)`) : null,
    s.real && s.real.gold != null ? stat(Number(s.real.gold).toLocaleString(), `Gold earned (${Math.round(s.real.gpm || 0)} a min)`) : null,
    s.real && s.real.lobby ? lobbyStat(s.real) : null,
    best ? el("button", { class: "btn btn-primary ms-post", onclick: () => openPlayer(best.id) }, `Post ${best.title}`) : null);
}
// post match analysis: a few plain sentences, CS over the game (you, your lane opponent, your usual) and CS by phase
function svgEl(tag, attrs = {}, ...kids) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v);
  for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}
const analysisTab = new Map();   // which tab (farming / combat / vision) is open for each match
// ---------------------------------------------------------------- the match analysis chart
// Drawn at the real pixel width of its box (redrawn when the window resizes), so text stays the same size
// however wide the window is. Smooth lines, a glow and soft fill under yours, the game's phases as bands,
// champion pictures at the end of each line, and a hover line that reads out every value at that minute.
const PHASE_BANDS = [["Lane", 0, 14], ["Mid", 14, 25], ["Late", 25, 999]];
function smoothPath(pts) {
  // monotone curve through the points (never overshoots, so CS never looks like it went down)
  const n = pts.length;
  if (n < 3) return pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  const dx = [], dy = [], m = [], t = [];
  for (let i = 0; i < n - 1; i++) { dx[i] = pts[i + 1][0] - pts[i][0]; dy[i] = pts[i + 1][1] - pts[i][1]; m[i] = dy[i] / dx[i]; }
  t[0] = m[0]; t[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (3 * (dx[i - 1] + dx[i])) / ((2 * dx[i] + dx[i - 1]) / m[i - 1] + (dx[i] + 2 * dx[i - 1]) / m[i]);
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += `C${(pts[i][0] + h).toFixed(1)},${(pts[i][1] + h * t[i]).toFixed(1)} ${(pts[i + 1][0] - h).toFixed(1)},${(pts[i + 1][1] - h * t[i + 1]).toFixed(1)} ${pts[i + 1][0].toFixed(1)},${pts[i + 1][1].toFixed(1)}`;
  }
  return d;
}
let chartId = 0;
function lineChart(c, deaths, keys) {
  const box = el("div", { class: "ma-chart-box" });
  const draw = () => {
    const W = Math.max(320, Math.round(box.clientWidth || 640)), H = 270, L = 40, R = 64, T = 30, B = 30;
    const id = "ch" + (++chartId);
    const lines = (c.lines || []).filter((l) => (l.pts || []).length > 1);
    const n = Math.max(2, ...lines.map((l) => l.pts.length));
    const rawTop = Math.max(5, ...lines.flatMap((l) => l.pts));
    const step = Math.pow(10, Math.floor(Math.log10(rawTop))) / 2;
    const top = Math.ceil((rawTop * 1.08) / step) * step;
    const x = (i) => L + (i / (n - 1)) * (W - L - R);
    const y = (v) => T + (1 - v / top) * (H - T - B);
    const kids = [svgEl("defs", {},
      svgEl("linearGradient", { id: id + "fill", x1: 0, y1: 0, x2: 0, y2: 1 },
        svgEl("stop", { offset: "0%", "stop-color": "#22d3ee", "stop-opacity": ".28" }),
        svgEl("stop", { offset: "100%", "stop-color": "#22d3ee", "stop-opacity": "0" })),
      svgEl("linearGradient", { id: id + "stroke", x1: 0, y1: 0, x2: 1, y2: 0 },
        svgEl("stop", { offset: "0%", "stop-color": "#0891b2" }), svgEl("stop", { offset: "100%", "stop-color": "#67e8f9" })),
      svgEl("filter", { id: id + "glow", x: "-10%", y: "-30%", width: "120%", height: "160%" },
        svgEl("feGaussianBlur", { stdDeviation: 4, result: "b" }),
        svgEl("feMerge", {}, svgEl("feMergeNode", { in: "b" }), svgEl("feMergeNode", { in: "SourceGraphic" }))),
      svgEl("pattern", { id: id + "hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
        svgEl("line", { x1: 0, y1: 0, x2: 0, y2: 6, class: "ch-hatch" })),
      svgEl("clipPath", { id: id + "round" }, svgEl("circle", { cx: 11, cy: 11, r: 11 })))];
    // the game's phases as soft bands with a label on top
    PHASE_BANDS.forEach(([name, a, b], i) => {
      if (a > n - 1) return;
      const x1 = x(a), x2 = x(Math.min(b, n - 1));
      kids.push(svgEl("rect", { x: x1, y: T, width: Math.max(0, x2 - x1), height: H - T - B, class: i % 2 ? "ch-band alt" : "ch-band" }),
        svgEl("text", { x: (x1 + x2) / 2, y: T - 10, class: "ch-phase", "text-anchor": "middle" }, name.toUpperCase()));
    });
    if (c.weak) kids.push(svgEl("rect", { x: x(c.weak[0]), y: T, width: Math.max(2, x(c.weak[1]) - x(c.weak[0])), height: H - T - B, fill: `url(#${id}hatch)` }));
    for (let k = 0; k <= 4; k++) {
      const v = (top * k) / 4;
      kids.push(svgEl("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: k ? "ch-grid" : "ch-axis" }),
        svgEl("text", { x: L - 10, y: y(v) + 4, class: "ch-tick", "text-anchor": "end" }, String(Math.round(v))));
    }
    const every = n > 40 ? 10 : 5;
    for (let m = 0; m < n; m += every) kids.push(svgEl("text", { x: x(m), y: H - 10, class: "ch-tick", "text-anchor": "middle" }, m ? `${m}m` : "0"));
    for (const d of deaths || []) if (d <= n - 1) kids.push(
      svgEl("line", { x1: x(d), x2: x(d), y1: T, y2: H - B, class: "ch-death" }),
      svgEl("circle", { cx: x(d), cy: H - B, r: 4, class: "ch-death-dot" }));
    // lines: others first, yours on top with a glow and a fill
    const order = [...lines].sort((p, q) => (p.style === "you") - (q.style === "you"));
    for (const l of order) {
      const pts = l.pts.map((v, i) => [x(i), y(v)]);
      const d = smoothPath(pts);
      if (l.style === "you") {
        kids.push(svgEl("path", { d: d + `L${x(l.pts.length - 1)},${y(0)}L${x(0)},${y(0)}Z`, fill: `url(#${id}fill)` }),
          svgEl("path", { d, class: "ch-you", stroke: `url(#${id}stroke)`, filter: `url(#${id}glow)` }));
      } else kids.push(svgEl("path", { d, class: "ch-" + l.style }));
    }
    // the end of each line: a dot, its value and the champion's picture
    const ends = lines.map((l) => ({ l, v: l.pts[l.pts.length - 1], i: l.pts.length - 1 })).sort((p, q) => q.v - p.v);
    let lastY = -99;
    for (const e of ends) {
      const ex = x(e.i), ey = y(e.v);
      const ly = Math.max(ey, lastY + 26); lastY = ly;
      kids.push(svgEl("circle", { cx: ex, cy: ey, r: e.l.style === "you" ? 5 : 4, class: "ch-end " + e.l.style }));
      const key = (keys || {})[e.l.style];
      const url = key && ddVersion && ddVersion !== "pending" ? `https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${key}.png` : "";
      const g = svgEl("g", { transform: `translate(${ex + 10},${ly - 11})` });
      if (url) g.append(svgEl("image", { href: url, width: 22, height: 22, "clip-path": `url(#${id}round)` }), svgEl("circle", { cx: 11, cy: 11, r: 11, class: "ch-ring " + e.l.style }));
      g.append(svgEl("text", { x: url ? 27 : 0, y: 15, class: "ch-endval " + e.l.style }, String(Math.round(e.v))));
      kids.push(g);
    }
    // hover: a line and a little card with every value at that minute
    const hover = svgEl("g", { class: "ch-hover", style: "display:none" });
    const hLine = svgEl("line", { y1: T, y2: H - B, class: "ch-hline" });
    const hBox = svgEl("rect", { rx: 8, class: "ch-hbox" });
    const hText = svgEl("text", { class: "ch-htext" });
    const hDots = lines.map((l) => svgEl("circle", { r: 4, class: "ch-hdot " + l.style }));
    hover.append(hLine, ...hDots, hBox, hText);
    kids.push(hover);
    const hit = svgEl("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" });
    hit.addEventListener("mousemove", (ev) => {
      const r = svg.getBoundingClientRect();
      const i = Math.max(0, Math.min(n - 1, Math.round(((ev.clientX - r.left - L) / (W - L - R)) * (n - 1))));
      hover.style.display = "";
      hLine.setAttribute("x1", x(i)); hLine.setAttribute("x2", x(i));
      lines.forEach((l, k) => {
        const v = l.pts[Math.min(i, l.pts.length - 1)];
        hDots[k].setAttribute("cx", x(Math.min(i, l.pts.length - 1))); hDots[k].setAttribute("cy", y(v));
      });
      hText.replaceChildren(svgEl("tspan", { x: 0, dy: 0, class: "ch-hmin" }, `${i} min`),
        ...lines.map((l) => svgEl("tspan", { x: 0, dy: 17, class: "ch-hrow " + l.style }, `${l.name}: ${Math.round(l.pts[Math.min(i, l.pts.length - 1)])}`)));
      const bw = 18 + Math.max(60, ...lines.map((l) => (l.name.length + 6) * 7)), bh = 26 + lines.length * 17;
      const bx = x(i) + 12 + bw > W - R ? x(i) - 12 - bw : x(i) + 12, by = T + 6;
      hBox.setAttribute("x", bx); hBox.setAttribute("y", by); hBox.setAttribute("width", bw); hBox.setAttribute("height", bh);
      hText.setAttribute("transform", `translate(${bx + 10},${by + 18})`);
    });
    hit.addEventListener("mouseleave", () => { hover.style.display = "none"; });
    kids.push(hit);
    const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: "ma-chart", role: "img",
      "aria-label": c.chart + ": " + lines.map((l) => `${l.name} ${Math.round(l.pts[l.pts.length - 1])}`).join(", ") }, kids);
    box.replaceChildren(svg);
  };
  let lastW = 0;
  new ResizeObserver(() => { if (Math.abs(box.clientWidth - lastW) > 4) { lastW = box.clientWidth; draw(); } }).observe(box);
  requestAnimationFrame(draw);
  return box;
}
function gauge(score) {
  // a 240 degree arc like a speedo, filled to the score
  const r = 42, cx = 50, cy = 52, start = 150, sweep = 240;
  const pt = (deg) => [cx + r * Math.cos((deg * Math.PI) / 180), cy + r * Math.sin((deg * Math.PI) / 180)];
  const arc = (from, to) => {
    const [x1, y1] = pt(from), [x2, y2] = pt(to);
    return `M${x1.toFixed(2)},${y1.toFixed(2)}A${r},${r} 0 ${to - from > 180 ? 1 : 0} 1 ${x2.toFixed(2)},${y2.toFixed(2)}`;
  };
  const cls = score < 35 ? "g-poor" : score < 55 ? "g-fair" : "g-good";
  return svgEl("svg", { viewBox: "0 0 100 92", class: "ma-gauge", "aria-hidden": "true" },
    svgEl("path", { d: arc(start, start + sweep), class: "g-track" }),
    svgEl("path", { d: arc(start, start + Math.max(1, (sweep * score) / 100)), class: "g-fill " + cls }),
    svgEl("text", { x: 50, y: 60, "text-anchor": "middle", class: "g-num" }, String(score)));
}
function withNumbers(text) {
  // the numbers in a tip stand out, like "4.0 CS a minute"
  const out = [];
  let last = 0;
  for (const m of text.matchAll(/\d(?:[\d.,:]*\d)?%?/g)) {
    out.push(text.slice(last, m.index), el("b", {}, m[0]));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}
function fmtBar(v, f) {
  return v == null ? "" : f === "%" ? `${v}%` : f === "2" ? v.toFixed(2) : f === "1" ? Number(v).toFixed(1) : String(v);
}
// small pictures: a champion from Riot's Data Dragon, a rank crest from OP.GG
function champPic(key, cls = "pic") {
  if (!key || !ddVersion || ddVersion === "pending") return null;
  return el("img", { class: cls, alt: "", src: `https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/${key}.png`,
    onerror: (e) => e.target.remove() });
}
function rankPic(tier, cls = "pic") {
  const t = String(tier || "").split(" ")[0].toLowerCase();
  if (!t || t === "all") return null;
  return el("img", { class: cls + " crest", alt: "", src: `https://opgg-static.akamaized.net/images/medals_new/${t}.png`, onerror: (e) => e.target.remove() });
}
const analysisOpen = new Set();   // matches whose analysis is open (closed by default)
function oppKey(a) {
  // the lane opponent's Data Dragon name; older games only kept the display name ("Kai'Sa" -> "Kaisa")
  if (a.opp_key) return a.opp_key;
  const n = (a.opp_name || "").replace(/[^A-Za-z0-9]/g, "");
  const odd = { KaiSa: "Kaisa", KhaZix: "Khazix", ChoGath: "Chogath", VelKoz: "Velkoz", LeBlanc: "Leblanc", BelVeth: "Belveth",
    Wukong: "MonkeyKing", RenataGlasc: "Renata", NunuWillump: "Nunu", KogMaw: "KogMaw", RekSai: "RekSai" };
  return odd[n] || n;
}
function matchAnalysis(a, champ, id, champKey) {
  if (!a.cats) return null;    // from an older version of the app
  if (!analysisOpen.has(id)) {
    // closed: one row with the three scores, click to open
    const chip = (k) => {
      const sc = a.cats[k].score;
      return el("span", { class: "mac-chip " + (sc < 35 ? "g-poor" : sc < 55 ? "g-fair" : "g-good") },
        el("b", {}, String(sc)), a.cats[k].title);
    };
    return el("button", { class: "m-analysis-closed", "aria-expanded": "false",
        onclick: () => { analysisOpen.add(id); renderClips(); } },
      el("span", { class: "mac-title" }, "Match analysis"),
      el("span", { class: "mac-chips" }, ["farming", "combat", "vision"].map(chip)),
      el("span", { class: "mac-open" }, "Show", el("span", { class: "mac-chev", "aria-hidden": "true" })));
  }
  const keys = ["farming", "combat", "vision"];
  const tab = analysisTab.get(id) || "farming";
  const c = a.cats[tab];
  const bars = c.bars || [];
  const h = c.headline;
  const okey = oppKey(a);
  const legend = el("div", { class: "ma-legend" }, (c.lines || []).filter((l) => (l.pts || []).length > 1)
    .map((l) => el("span", { class: "lg-" + l.style },
      tab === "farming" && l.style === "you" ? champPic(champKey, "lg-pic") : tab === "farming" && l.style === "opp" ? champPic(okey, "lg-pic") : null,
      l.style === "you" && tab === "farming" && champ ? `You (${champ})` : l.name)),
    tab === "combat" && (a.deaths || []).length ? el("span", { class: "lg-death" }, "Your deaths") : null,
    c.weak ? el("span", { class: "lg-weak" }, "Where it dropped") : null);
  return el("section", { class: "m-analysis", "aria-label": "Match analysis" },
    el("div", { class: "ma-head" },
      el("h4", {}, "Match analysis"),
      el("span", { class: "ma-vs" }, "Compared with ",
        c.vs === a.opp_name && okey ? champPic(okey, "vs-pic") : null,
        el("b", {}, c.vs_rank ? `${c.vs} and ${c.vs_rank} players` : c.vs)),

      a.rank ? el("span", { class: "ma-rank" },
        a.rank.image ? el("img", { src: a.rank.image, alt: "", onerror: (e) => e.target.remove() }) : null,
        a.rank.text, a.rank.lp != null ? el("small", {}, ` ${a.rank.lp} LP`) : null) : null,
      el("div", { class: "ma-tabs", role: "tablist" }, keys.map((k) => el("button", {
        role: "tab", "aria-selected": String(k === tab), class: k === tab ? "on" : "",
        onclick: () => { analysisTab.set(id, k); renderClips(); } }, a.cats[k].title))),
      el("button", { class: "ma-close", "aria-label": "Hide match analysis", title: "Hide",
        onclick: () => { analysisOpen.delete(id); renderClips(); } }, "Hide", el("span", { class: "mac-chev up", "aria-hidden": "true" }))),
    el("div", { class: "ma-body" },
      el("div", { class: "ma-score" },
        el("div", { class: "ma-score-top" },
          champ ? el("div", { class: "ma-champ" }, champPic(champKey, "ma-champ-pic"), el("span", {}, champ)) : null,
          gauge(c.score), el("strong", {}, c.title), el("span", {}, c.rating)),
        bars.map((b) => {
          const worse = b.usual != null && (b.lower ? b.you > b.usual : b.you < b.usual * 0.92);
          // each bar on its own scale: a bit past the bigger of yours and your usual (deaths: out of 10)
          const maxV = b.lower ? Math.max(10, b.you) : Math.max(0.01, b.you || 0, b.usual || 0) * 1.25;
          return el("div", { class: "ma-bar" },
            el("div", { class: "mb-row" },
              el("span", { class: "mb-name" },
                b.icon === "rank" ? rankPic(b.tier || (a.rank && a.rank.tier)) : b.icon === "champ" ? champPic(champKey) : null, b.name),
              el("b", {}, fmtBar(b.you, b.fmt) + (b.usual != null ? ` / ${fmtBar(b.usual, b.fmt)}` : ""))),
            el("span", { class: "ph-bar" },
              el("i", { class: worse ? "ph-down" : "", style: `width:${Math.min(100, ((b.you || 0) / maxV) * 100)}%` }),
              b.usual != null ? el("b", { style: `left:${(b.usual / maxV) * 100}%`, title: "Your usual" }) : null));
        })),
      el("div", { class: "ma-main" },
        el("h5", {}, c.title + " performance"),
        el("p", { class: "ma-headline" }, h ? withNumbers(h.text) : "Nothing stood out here this game."),
        lineChart(c, tab === "combat" ? a.deaths : null, tab === "farming" ? { you: champKey, opp: okey } : {}), legend,
        (a.tips || []).filter((t) => t.cat === tab && t !== h).length
          ? el("ul", { class: "ma-tips" }, a.tips.filter((t) => t.cat === tab && t.text !== (h && h.text))
            .map((t) => el("li", { class: "t-" + t.kind }, withNumbers(t.text)))) : null)));
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
  const ih = (r.config.item_ideas_hotkey || "alt+shift+i").toUpperCase().replace(/\+/g, " + ");
  $("#items-hotkey-btn").textContent = ih;
  for (const k of $$("[data-items-hotkey]")) k.textContent = ih;
  $("#box-hotkey-btn").textContent = (r.config.lol_box_hotkey || "alt+shift+b").toUpperCase().replace(/\+/g, " + ");
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

  // two shortcut buttons: saving a clip, and League stats + item ideas
  let hk = $("#hotkey-btn"), hkSetting = "hotkey";
  for (const [btn, setting] of [[$("#hotkey-btn"), "hotkey"], [$("#items-hotkey-btn"), "item_ideas_hotkey"], [$("#box-hotkey-btn"), "lol_box_hotkey"]]) {
    btn.addEventListener("click", () => {
      if (listening) hk.classList.remove("listening");
      hk = btn; hkSetting = setting;
      listening = true;
      btn.classList.add("listening");
      btn.textContent = "Press keys...";
    });
  }
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
    await setSetting(hkSetting, combo);
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
