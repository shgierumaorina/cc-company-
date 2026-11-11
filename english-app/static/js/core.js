/* リスニング・ラボ（クラウド版） */
"use strict";
/* リスニング・ラボ フロントエンド（依存ライブラリなし） */
"use strict";

const $app = document.getElementById("app");
const player = document.getElementById("player");
let S = null;            // サーバーの状態
let talks = [];          // 会話履歴の一覧
let pollTimer = null;

// ---------- 共通 ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fmt = (sec) => { sec = Math.max(0, Math.floor(sec || 0)); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`; };
const ICON = {
  play: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="7 4 20 12 7 20 7 4"/></svg>',
  pause: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><line x1="8" y1="5" x2="8" y2="19"/><line x1="16" y1="5" x2="16" y2="19"/></svg>',
  back: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7"/><polyline points="3 3 3 9 9 9"/></svg>',
  repeat: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/></svg>',
  mic: '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><line x1="12" y1="18" x2="12" y2="21"/></svg>',
  star: '<svg width="18" height="18" viewBox="0 0 24 24" fill="FILL" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="12 2 15.1 8.3 22 9.3 17 14.1 18.2 21 12 17.8 5.8 21 7 14.1 2 9.3 8.9 8.3 12 2"/></svg>',
  speaker: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>',
};
const CAUSES = [
  { id: "sound", label: "音の変化", color: "var(--blue)", hex: "#1F4FC4", hint: "字幕を見たら知っている単語だった" },
  { id: "speed", label: "処理速度", color: "var(--orange)", hex: "#B85C00", hint: "ゆっくりなら分かる" },
  { id: "chunk", label: "かたまり表現", color: "var(--purple)", hex: "#7A3FB8", hint: "単語は分かるが意味が取れない" },
  { id: "flow", label: "話の流れ", color: "var(--teal)", hex: "#0F766E", hint: "何の話か見失った" },
];

function toast(msg, ms = 3200) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), ms);
}

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (e) { /* noop */ }
  if (!r.ok || data.error) throw new Error(data.error || `エラー (${r.status})`);
  if (data && data.config && data.episodes) S = data;
  return data;
}
async function refresh() { await api("/api/state"); }

function busy(btn, on, label) {
  if (!btn) return;
  if (on) { btn.dataset.label = btn.innerHTML; btn.innerHTML = `<span class="spin"></span> ${label || "処理中"}`; btn.disabled = true; }
  else { btn.innerHTML = btn.dataset.label || btn.innerHTML; btn.disabled = false; }
}

// ---------- データの集計 ----------
const readyEps = () => S.episodes.filter((e) => e.status === "ready");
const doneSet = () => new Set(S.progress.sessions.map((s) => `${s.ep}:${s.idx}`));
const dueReviews = () => S.progress.review.filter((r) => !r.done && r.due <= S.today);

function nextSection() {
  const done = doneSet();
  for (const e of readyEps()) {
    for (let i = 0; i < (e.sections || 0); i++) if (!done.has(`${e.id}:${i}`)) return { ep: e, idx: i };
  }
  return null;
}
function weekKey(dateStr) {
  const d = new Date(dateStr + "T00:00:00"); const day = (d.getDay() + 6) % 7; d.setDate(d.getDate() - day);
  return ymd(d);
}
function accuracyByWeek(n = 6) {
  const now = weekKey(S.today); const out = [];
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(now + "T00:00:00"); d.setDate(d.getDate() - 7 * i);
    const k = ymd(d);
    const ss = S.progress.sessions.filter((s) => weekKey(s.date) === k && s.correct !== null && s.correct !== undefined);
    out.push({ key: k, label: i === 0 ? "今週" : `${i}週前`, n: ss.length, val: ss.length ? Math.round(100 * ss.filter((s) => s.correct).length / ss.length) : null, now: i === 0 });
  }
  return out;
}
function activeDays() {
  const days = new Set(S.progress.sessions.map((s) => s.date));
  talks.forEach((t) => days.add(t.started.slice(0, 10)));
  return days;
}
function streak() {
  const days = activeDays(); let n = 0; const d = new Date(S.today + "T00:00:00");
  if (!days.has(S.today)) d.setDate(d.getDate() - 1);
  while (days.has(ymd(d))) { n++; d.setDate(d.getDate() - 1); }
  return n;
}
function causeCounts(fromDays, toDays) {
  const c = {}; CAUSES.forEach((x) => (c[x.id] = 0));
  const start = new Date(S.today + "T00:00:00"); start.setDate(start.getDate() - fromDays);
  const end = new Date(S.today + "T00:00:00"); end.setDate(end.getDate() - toDays);
  S.progress.sessions.forEach((s) => {
    const d = new Date(s.date + "T00:00:00");
    if (d > start && d <= end) s.missed.forEach((m) => { if (m.cause && c[m.cause] !== undefined) c[m.cause]++; });
  });
  return c;
}

// ---------- ルーティング ----------
const routes = {};
function go(hash) { location.hash = hash; }
async function render() {
  const [name, ...args] = (location.hash.slice(1) || "home").split("/");
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === (name === "listen" || name === "check" ? "home" : name === "talk" ? "theme" : name === "yt" ? "shows" : name)));
  stopPlayer(); stopRec(); clearInterval(pollTimer);
  window.speechSynthesis && speechSynthesis.cancel();
  try {
    if (!S) await refresh();
    await (routes[name] || routes.home)(...args.map(decodeURIComponent));
  } catch (e) {
    $app.innerHTML = `<div class="card empty">読み込みに失敗しました：${esc(e.message)}<br><br><a href="#home">ホームへ</a></div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", render);

// ---------- プレーヤー ----------
let stopAt = null, loop = null, onTick = null, stopFrame = null;
function checkStop() {
  if (stopAt !== null && player.currentTime >= stopAt) {
    if (loop) { player.currentTime = loop; } else { player.pause(); stopAt = null; }
  }
}
// timeupdate は約0.25秒おきにしか来ず止まるのが遅れるため、再生中は画面の描画ごと（約0.016秒）に確認する
function watchStop() {
  cancelAnimationFrame(stopFrame);
  const tick = () => { checkStop(); if (stopAt !== null && !player.paused) stopFrame = requestAnimationFrame(tick); };
  stopFrame = requestAnimationFrame(tick);
}
player.addEventListener("timeupdate", () => { checkStop(); onTick && onTick(); });
player.addEventListener("play", () => { watchStop(); onTick && onTick(); });
player.addEventListener("pause", () => onTick && onTick());
function stopPlayer() { player.pause(); stopAt = null; loop = null; onTick = null; }
// ロック画面・イヤホンのボタンで操作できるように
function mediaSession(title, artist, handlers) {
  if (!("mediaSession" in navigator)) return;
  try {
    navigator.mediaSession.metadata = new MediaMetadata({ title, artist, album: "リスニング・ラボ", artwork: [{ src: "/static/icon-512.png", sizes: "512x512", type: "image/png" }] });
    ["play", "pause", "seekbackward", "seekforward", "previoustrack", "nexttrack"].forEach((a) => {
      try { navigator.mediaSession.setActionHandler(a, handlers[a] || null); } catch (e) { /* noop */ }
    });
  } catch (e) { /* noop */ }
}
function playRange(src, from, to, rate, silent) {
  if (!player.src.endsWith(src)) player.src = src;
  player.playbackRate = rate || 1;
  const go = () => { player.currentTime = from; stopAt = to; player.play().catch(() => { if (!silent) toast("再生できませんでした"); }); };
  if (player.readyState >= 1) go(); else player.addEventListener("loadedmetadata", go, { once: true });
}

function localGet(k, d) { try { const v = localStorage.getItem("ll_" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }
function localSet(k, v) { try { localStorage.setItem("ll_" + k, JSON.stringify(v)); } catch (e) { /* noop */ } }
