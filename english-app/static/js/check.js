"use strict";
/* 答え合わせ・復習 */
// ================= 答え合わせ =================
function highlight(text, chunks) {
  let html = esc(text);
  (chunks || []).forEach((c) => {
    const words = (c.en || "").replace(/[〜~].*$/, "").trim();
    if (words.length < 3) return;
    // 活用形も拾う（end up → ended up / ending up）
    const pat = words.split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\w*").join("\\s+");
    const re = new RegExp(`\\b(${pat})`, "i");
    html = html.replace(re, '<mark class="chunk">$1</mark>');
  });
  return html;
}
routes.check = async (epId, idx) => {
  idx = +idx;
  const d = await api(`/api/episode/${epId}`);
  const s = d.sections[idx];
  if (!L || L.ep !== epId || L.idx !== idx) L = { ep: epId, idx, choice: null, feel: null, missed: {}, cause: {}, rate: 1, showJa: false };
  const src = `/audio/${epId}`;
  const hasQ = s.choices && s.choices.length;
  const unknown = L.choice === (s.choices || []).length;
  const correct = hasQ && L.choice !== null ? L.choice === s.answer : null;

  const draw = () => {
    const missedN = Object.values(L.missed).filter(Boolean).length;
    $app.innerHTML = `<div class="has-acts"><div class="small" style="margin-bottom:14px"><a href="#listen/${epId}/${idx}">← もう一度聞く</a> ・ 区間 ${idx + 1} / ${d.sections.length} ・ ステップ 2/2 答え合わせ</div>
    <div class="row">
      <div class="grow stack">
        ${hasQ ? `<section class="banner ${correct ? "ok" : ""}">
          要旨チェック：<b>${L.choice === null ? "未回答" : correct ? "正解！" : unknown ? "わからなかった" : "不正解"}</b>
          ${correct === false && !unknown ? `（あなた ${String.fromCharCode(65 + L.choice)} ／ 正解 ${String.fromCharCode(65 + s.answer)}）` : ""}
          <div style="margin-top:4px">正解：${esc(s.choices[s.answer] || "")}</div>
          ${s.summary_ja ? `<div class="small" style="margin-top:4px">要旨：${esc(s.summary_ja)}</div>` : ""}
        </section>` : ""}
        <section class="card">
          <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px">
            <h2 style="margin:0">文字起こし</h2>
            <button class="btn plain sm" id="jaBtn">${L.showJa ? "日本語訳を隠す" : "日本語訳を表示"}</button>
          </div>
          <p class="note">聞き取れなかった文に印を付けて、原因を選びます。▶で1文ずつ再生。</p>
          <div id="lines">${s.lines.map((ln, i) => `<div class="line" data-li="${i}">
            <div class="main">
              <button class="iconbtn" data-play="${i}" aria-label="この文を再生">${ICON.play}</button>
              <div class="txt"><div class="en">${highlight(ln.text, s.chunks)}</div>${L.showJa && ln.ja ? `<div class="ja">${esc(ln.ja)}</div>` : ""}</div>
              <button class="miss ${L.missed[i] ? "on" : ""}" data-miss="${i}">${L.missed[i] ? "聞き取れなかった" : "聞けた"}</button>
            </div>
            ${L.missed[i] ? `<div class="tags">${CAUSES.map((c) => `<button class="tag" data-li2="${i}" data-cause="${c.id}" style="color:${L.cause[i] === c.id ? "#fff" : c.color};${L.cause[i] === c.id ? `background:${c.color};border-color:${c.color}` : ""}" title="${esc(c.hint)}">${c.label}</button>`).join("")}</div>` : ""}
          </div>`).join("")}</div>
        </section>
      </div>
      <aside class="side stack">
        <section class="card"><h2>この区間のかたまり表現</h2>
          ${(s.chunks || []).map((c) => `<div style="padding:10px 0;border-top:1px solid var(--line2)"><div style="font-weight:700;color:var(--purpleInk)">${esc(c.en)}</div><div style="font-size:13px">${esc(c.ja)}</div></div>`).join("") || '<p class="note">まだありません</p>'}
        </section>
        <section class="card"><h2>原因タグの目安</h2>
          <div style="font-size:13px;line-height:1.8">${CAUSES.map((c) => `<b style="color:${c.color}">${c.label}</b>：${c.hint}`).join("<br>")}</div>
        </section>
        <div class="acts">
          <button class="btn" id="saveTalk">記録して会話へ</button>
          <button class="btn ghost" id="saveEnd">記録して終了（復習${missedN}文）</button>
        </div>
      </aside>
    </div></div>`;
    bind();
  };

  const bind = () => {
    onTick = () => {
      document.querySelectorAll(".line").forEach((el) => {
        const ln = s.lines[+el.dataset.li];
        el.classList.toggle("playing", !player.paused && player.currentTime >= ln.start && player.currentTime < ln.end);
      });
    };
    document.querySelectorAll("[data-play]").forEach((b) => (b.onclick = () => {
      // 前後の文に入り込まないよう、前の文の終わり〜次の文の始まりの範囲に収める
      const i = +b.dataset.play, ln = s.lines[i], prev = s.lines[i - 1], next = s.lines[i + 1];
      const from = Math.min(ln.start, Math.max(prev ? prev.end : 0, ln.start - 0.15));
      const to = next ? Math.max(ln.start + 0.3, Math.min(ln.end + 0.1, next.start)) : ln.end + 0.2;
      playRange(src, from, to, L.rate);
    }));
    document.querySelectorAll("[data-miss]").forEach((b) => (b.onclick = () => { const i = +b.dataset.miss; L.missed[i] = !L.missed[i]; draw(); }));
    document.querySelectorAll("[data-cause]").forEach((b) => (b.onclick = () => { L.cause[+b.dataset.li2] = b.dataset.cause; draw(); }));
    document.getElementById("jaBtn").onclick = async (e) => {
      if (L.showJa) { L.showJa = false; draw(); return; }
      if (!s.lines.every((l) => l.ja)) {
        busy(e.currentTarget, true, "翻訳中");
        try { const r = await api("/api/translate", { ep: epId, idx }); s.lines = r.lines; }
        catch (err) { toast(err.message); busy(e.currentTarget, false); return; }
      }
      L.showJa = true; draw();
    };
    const save = async (next) => {
      const missed = Object.keys(L.missed).filter((k) => L.missed[k]).map((k) => { const ln = s.lines[+k]; return { line: +k, text: ln.text, ja: ln.ja || "", start: ln.start, end: ln.end, cause: L.cause[k] || null }; });
      if (missed.some((m) => !m.cause)) { if (!confirm("原因タグが未選択の文があります。このまま記録しますか？")) return; }
      try {
        await api("/api/session", { ep: epId, idx, choice: L.choice, correct, feel: L.feel, lines: s.lines.length, missed });
        L = null; toast("記録しました"); go(next);
      } catch (err) { toast(err.message); }
    };
    document.getElementById("saveTalk").onclick = () => save(`theme/${epId}/${idx}`);
    document.getElementById("saveEnd").onclick = () => save("home");
  };
  draw();
};

// ================= 復習 =================
routes.review = async () => {
  const items = dueReviews();
  let i = 0, shown = false;
  const draw = () => {
    if (i >= items.length) {
      $app.innerHTML = `<div class="card empty" style="max-width:720px;margin:0 auto">${items.length ? "今日の復習は完了です！" : "今日復習する文はありません。"}<br><br><a class="btn" href="#home">ホームへ</a></div>`;
      return;
    }
    const it = items[i]; const cause = CAUSES.find((c) => c.id === it.cause);
    const ep = S.episodes.find((e) => e.id === it.ep);
    $app.innerHTML = `<div class="stack" style="max-width:760px;margin:0 auto">
      <div class="small">復習 ${i + 1} / ${items.length} ${cause ? `・ 原因：<b style="color:${cause.color}">${cause.label}</b>` : ""}</div>
      <section class="card stack" style="align-items:center;text-align:center">
        <p class="note">${esc(ep ? ep.title : "")}</p>
        <div class="controls">
          <button class="round" id="rp" aria-label="再生">${ICON.play}</button>
          <button class="chip" id="rslow">0.75xで再生</button>
        </div>
        <div style="min-height:80px;display:flex;flex-direction:column;gap:6px;justify-content:center">
          ${shown ? `<div style="font-size:19px">${esc(it.text)}</div>${it.ja ? `<div class="note">${esc(it.ja)}</div>` : ""}` : `<button class="btn plain" id="show">英文を見る</button>`}
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:center">
          <button class="btn ghost" id="ng">まだ聞き取れない</button>
          <button class="btn" id="ok">聞き取れた</button>
        </div>
        <button class="small" id="rmrev" style="background:none;border:none;color:var(--muted);text-decoration:underline;cursor:pointer">この文を復習リストから削除</button>
      </section></div>`;
    const play = (r, silent) => playRange(`/audio/${it.ep}`, Math.max(0, it.start - 0.15), it.end + 0.1, r, silent);
    mediaSession("復習", ep ? ep.title : "", { play: () => play(1), pause: () => player.pause(), previoustrack: () => play(1) });
    document.getElementById("rp").onclick = () => play(1);
    document.getElementById("rslow").onclick = () => play(0.75);
    const sh = document.getElementById("show"); if (sh) sh.onclick = () => { shown = true; draw(); };
    const ans = async (ok) => { try { await api("/api/review/answer", { id: it.id, ok }); } catch (e) { toast(e.message); } i++; shown = false; draw(); };
    document.getElementById("ok").onclick = () => ans(true);
    document.getElementById("ng").onclick = () => ans(false);
    document.getElementById("rmrev").onclick = async () => { try { await api("/api/review/delete", { id: it.id }); toast("削除しました"); } catch (e) { toast(e.message); } i++; shown = false; draw(); };
    if (!shown) play(1, true);
  };
  draw();
};

