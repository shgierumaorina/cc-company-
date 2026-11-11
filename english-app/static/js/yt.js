"use strict";
/* YouTube（聞くだけ）と起動 */
// ================= YouTube（聞くだけ） =================
let ytApi = null;
function loadYt() {
  if (ytApi) return ytApi;
  ytApi = new Promise((res) => { window.onYouTubeIframeAPIReady = () => res(window.YT); const s = document.createElement("script"); s.src = "https://www.youtube.com/iframe_api"; document.head.appendChild(s); });
  return ytApi;
}
routes.yt = async (id) => {
  const y = S.config.youtube.find((v) => v.id === id);
  if (!y) { go("shows"); return; }
  let A = null, B = null, rate = 1;
  $app.innerHTML = `<div class="stack" style="max-width:900px;margin:0 auto">
    <div class="small"><a href="#shows">← 番組と音源</a> ・ 聞くだけモード</div>
    <div class="yt"><div id="ytp"></div></div>
    <section class="card stack">
      <h2 style="margin:0">${esc(y.title)}</h2>
      <div class="controls">
        <button class="chip" id="b5">${ICON.back}5秒戻る</button>
        <button class="chip" id="setA">区間の開始 A</button><button class="chip" id="setB">区間の終了 B</button><button class="chip" id="clr">区間解除</button>
      </div>
      <div class="controls">${[0.75, 0.9, 1, 1.25].map((r) => `<button class="chip ${r === 1 ? "on" : ""}" data-yr="${r}">${r}x</button>`).join("")}</div>
      <p class="note" id="ab" style="text-align:center">AとBを押すと、その間をくり返し再生します</p>
    </section></div>`;
  const YT = await loadYt();
  const p = new YT.Player("ytp", { videoId: y.video_id, playerVars: { rel: 0, cc_load_policy: 0 } });
  const ab = () => (document.getElementById("ab").textContent = A !== null && B !== null ? `区間リピート中：${fmt(A)}〜${fmt(B)}` : A !== null ? `開始 ${fmt(A)}（終了Bを押してください）` : "AとBを押すと、その間をくり返し再生します");
  const tick = setInterval(() => { if (!document.getElementById("ytp")) { clearInterval(tick); return; } try { if (A !== null && B !== null && p.getCurrentTime() >= B) p.seekTo(A, true); } catch (e) { /* noop */ } }, 250);
  document.getElementById("b5").onclick = () => p.seekTo(Math.max(0, p.getCurrentTime() - 5), true);
  document.getElementById("setA").onclick = () => { A = p.getCurrentTime(); B = null; ab(); };
  document.getElementById("setB").onclick = () => { if (A === null) return; B = p.getCurrentTime(); if (B <= A) { B = null; toast("Bは Aより後にしてください"); } else p.seekTo(A, true); ab(); };
  document.getElementById("clr").onclick = () => { A = B = null; ab(); };
  document.querySelectorAll("[data-yr]").forEach((b) => (b.onclick = () => { rate = +b.dataset.yr; p.setPlaybackRate(rate); document.querySelectorAll("[data-yr]").forEach((x) => x.classList.toggle("on", x === b)); }));
};

render();
