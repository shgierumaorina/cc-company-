"use strict";
/* 日常会話フレーズ：共通部品（下から出るカード・1回だけの音声認識・一致度） */
// ================= 日常会話フレーズ（共通） =================
const duePhrases = () => (S.progress.phrases || []).filter((p) => !p.done && p.due <= S.today);
const phraseKey = (en) => String(en || "").toLowerCase().trim();
const savedPhraseKeys = () => new Set((S.progress.phrases || []).map((p) => phraseKey(p.en)));
const REG_COLOR = { "カジュアル": ["var(--orangeSoft)", "var(--orange)"], "ふつう": ["var(--line2)", "var(--sub)"], "ていねい": ["var(--tealSoft)", "var(--teal)"] };
function regPill(r) { if (!r) return ""; const c = REG_COLOR[r] || REG_COLOR["ふつう"]; return `<span class="pill" style="background:${c[0]};color:${c[1]}">${esc(r)}</span>`; }
const ttsBtn = (text, label) => `<button class="chip sm" data-tts="${esc(text)}">${ICON.speaker}${label ? esc(label) : ""}</button>`;
function phraseDetailHtml(p) {
  return `${p.scene_ja ? `<div class="pd-row"><b>使う場面</b>${esc(p.scene_ja)}</div>` : ""}
    ${p.nuance_ja ? `<div class="pd-row"><b>ニュアンス</b>${esc(p.nuance_ja)}</div>` : ""}
    ${(p.alts || []).length ? `<div class="pd-row"><b>言い換え</b>${p.alts.map((a) => `<div class="pd-alt"><div><div>${esc(a.en)}</div>${a.ja ? `<div class="small">${esc(a.ja)}</div>` : ""}</div>${ttsBtn(a.en)}</div>`).join("")}</div>` : ""}
    ${p.context || p.quote ? `<div class="pd-row"><b>ポッドキャストでは</b><i>“${esc(p.context || p.quote)}”</i></div>` : ""}`;
}
function bindTts(root) { (root || document).querySelectorAll("[data-tts]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); speak(b.dataset.tts); })); }
// 下から出るカード
function closeSheet() { document.querySelectorAll(".sheet-bg").forEach((x) => x.remove()); document.body.classList.remove("noscroll"); }
function sheet(html) {
  closeSheet();
  const bg = document.createElement("div"); bg.className = "sheet-bg";
  bg.innerHTML = `<div class="sheet" role="dialog" aria-modal="true"><button class="sheet-x" aria-label="閉じる">×</button>${html}</div>`;
  bg.onclick = (e) => { if (e.target === bg) closeSheet(); };
  bg.querySelector(".sheet-x").onclick = closeSheet;
  document.body.appendChild(bg); document.body.classList.add("noscroll");
  bindTts(bg);
  return bg;
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });
// 1回だけ聞き取る（フレーズ練習用）
function listenOnce(onText, onEnd) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast("このブラウザは音声認識に対応していません。ChromeかEdgeで開いてください", 6000); return false; }
  stopRec(); speechSynthesis.cancel();
  rec = new SR(); rec.lang = "en-US"; rec.interimResults = true; rec.continuous = false;
  let said = "";
  rec.onresult = (ev) => { said = Array.from(ev.results).map((r) => r[0].transcript).join(" ").trim(); onText(said); };
  rec.onerror = (ev) => { if (ev.error === "not-allowed") toast("マイクの使用が許可されていません（アドレスバーの鍵アイコンから許可）", 6000); };
  rec.onend = () => { rec = null; recOn = false; onEnd(said); };
  rec.start(); recOn = true;
  return true;
}
const words = (s) => String(s || "").toLowerCase().replace(/[~〜…]/g, " ").replace(/[^a-z0-9' ]+/g, " ").split(/\s+/).filter(Boolean);
function matchScore(said, targets) {
  const sw = new Set(words(said)); let best = null;
  (targets || []).forEach((t) => {
    const tw = words(t).filter((w) => !["someone", "something", "sb", "sth"].includes(w)); if (!tw.length) return;
    const miss = tw.filter((w) => !sw.has(w)); const pct = Math.round(100 * (tw.length - miss.length) / tw.length);
    if (!best || pct > best.pct) best = { pct, miss, target: t };
  });
  return best || { pct: 0, miss: [], target: "" };
}
