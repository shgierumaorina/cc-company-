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
  if (!L || L.ep !== epId || L.idx !== idx) L = { ep: epId, idx, choice: null, feel: null, missed: {}, cause: {}, rate: 1, showJa: localGet("checkJa", true) };
  const src = `/audio/${epId}`;
  const hasQ = s.choices && s.choices.length;
  const unknown = L.choice === (s.choices || []).length;
  const correct = hasQ && L.choice !== null ? L.choice === s.answer : null;
  // ---- 日常会話フレーズ ----
  let phrState = s.phrases_v >= 1 ? "done" : "loading", phrErr = "";
  const loadPhrases = async (force) => {
    phrState = "loading"; if (force) draw();
    try { const r = await api("/api/phrases/section", { ep: epId, idx, force: !!force }); s.phrases = r.phrases; s.phrases_v = r.phrases_v; phrState = "done"; }
    catch (err) { phrState = "error"; phrErr = err.message; }
    if (location.hash.startsWith(`#check/${epId}/${idx}`)) draw();
  };
  const phrHtml = (text, i, byLine, phrs) => { // 文の中のフレーズに下線（かたまり表現の色付けはそのまま）
    for (const k of byLine[i] || []) {
      const q = String(phrs[k].quote || "").trim().replace(/[.,!?]+$/, "");
      const pos = q.length >= 3 ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
      if (pos >= 0) return highlight(text.slice(0, pos), s.chunks) + `<span class="phr" role="button" tabindex="0" data-ph="${k}">${highlight(text.slice(pos, pos + q.length), s.chunks)}</span>` + highlight(text.slice(pos + q.length), s.chunks);
    }
    return highlight(text, s.chunks);
  };
  const savePhrase = async (k) => {
    try { await api("/api/phrases/save", { ep: epId, idx, i: k }); toast("フレーズ帳に保存しました（明日から復習に出ます）"); } catch (err) { toast(err.message); }
    draw();
  };
  const openPhrase = (k) => {
    const p = s.phrases[k]; const ln = Number.isInteger(p.line) ? s.lines[p.line] : null; const sv = savedPhraseKeys().has(phraseKey(p.en));
    const bg = sheet(`<div class="small" style="color:var(--purple);font-weight:700">日常会話フレーズ</div>
      <div class="pr-en" style="margin:4px 0">${esc(p.en)} ${regPill(p.register)}</div><div>${esc(p.ja)}</div>
      <div class="controls" style="justify-content:flex-start;gap:8px;margin:10px 0">${ln ? `<button class="chip sm" id="shOrig">${ICON.play}原音</button>` : ""}${ttsBtn(p.en, "読み上げ")}</div>
      <div class="pd">${phraseDetailHtml({ ...p, context: ln ? ln.text : "" })}</div>
      <button class="btn ${sv ? "plain" : ""}" id="shSave" style="width:100%;margin-top:14px" ${sv ? "disabled" : ""}>${sv ? "保存済み" : "フレーズ帳に保存"}</button>`);
    const o = bg.querySelector("#shOrig"); if (o) o.onclick = () => playRange(src, Math.max(0, ln.start - 0.15), ln.end + 0.1, L.rate);
    bg.querySelector("#shSave").onclick = async () => { await savePhrase(k); closeSheet(); };
  };

  const draw = () => {
    const missedN = Object.values(L.missed).filter(Boolean).length;
    const phrs = s.phrases || []; const saved = savedPhraseKeys(); const byLine = {};
    phrs.forEach((p, k) => { if (Number.isInteger(p.line)) (byLine[p.line] = byLine[p.line] || []).push(k); });
    const unsaved = phrs.map((p, k) => k).filter((k) => !saved.has(phraseKey(phrs[k].en)));
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
          <div class="controls" id="speeds" style="margin-bottom:6px">${[0.75, 0.9, 1, 1.25].map((r) => `<button class="chip ${L.rate === r ? "on" : ""}" data-r="${r}">${r}x</button>`).join("")}</div>
          <div id="lines">${s.lines.map((ln, i) => `<div class="line" data-li="${i}">
            <div class="main">
              <button class="iconbtn" data-play="${i}" aria-label="この文を再生">${ICON.play}</button>
              <div class="txt"><div class="en notranslate" translate="no" lang="en">${phrHtml(ln.text, i, byLine, phrs)}</div>${L.showJa && ln.ja ? `<div class="ja">${esc(ln.ja)}</div>` : ""}${(byLine[i] || []).length ? `<div class="phr-tags">${byLine[i].map((k) => `<button class="phr-tag" data-ph="${k}">${ICON.chat}${esc(phrs[k].en)}${saved.has(phraseKey(phrs[k].en)) ? " ✓" : ""}</button>`).join("")}</div>` : ""}</div>
              <button class="miss ${L.missed[i] ? "on" : ""}" data-miss="${i}">${L.missed[i] ? "聞き取れなかった" : "聞けた"}</button>
            </div>
            ${L.missed[i] ? `<div class="tags">${CAUSES.map((c) => `<button class="tag" data-li2="${i}" data-cause="${c.id}" style="color:${L.cause[i] === c.id ? "#fff" : c.color};${L.cause[i] === c.id ? `background:${c.color};border-color:${c.color}` : ""}" title="${esc(c.hint)}">${c.label}</button>`).join("")}</div>` : ""}
          </div>`).join("")}</div>
        </section>
      </div>
      <aside class="side stack">
        <section class="card"><h2>日常会話フレーズ${phrs.length ? `<span class="cnt phr">${phrs.length}</span>` : ""}</h2>
          <p class="note" style="margin-bottom:4px">そのまま使える言い回し。保存すると復習と会話練習に出ます</p>
          ${phrs.map((p, k) => { const sv = saved.has(phraseKey(p.en)); return `<div class="phr-item"><button class="phr-open" data-ph="${k}"><div class="phr-en">${esc(p.en)}</div><div class="chk-ja">${esc(p.ja)}</div>${p.scene_ja ? `<div class="chk-note">${esc(p.scene_ja)}</div>` : ""}</button>
            <button class="btn sm ${sv ? "plain" : "ghost"}" data-save="${k}" ${sv ? "disabled" : ""}>${sv ? "保存済" : "保存"}</button></div>`; }).join("")}
          ${phrState === "loading" ? '<p class="note"><span class="spin"></span> 使えるフレーズを探しています…</p>'
            : phrState === "error" ? `<p class="note">フレーズを作れませんでした：${esc(phrErr)}</p><button class="btn plain sm" id="phrRetry">もう一度作る</button>`
            : phrs.length ? (unsaved.length > 1 ? `<button class="btn sm" id="phrAll" style="margin-top:8px">まとめて保存（${unsaved.length}）</button>` : "") : '<p class="note">この区間には見つかりませんでした</p>'}
        </section>
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
    document.querySelectorAll("#speeds [data-r]").forEach((b) => (b.onclick = () => { L.rate = +b.dataset.r; player.playbackRate = L.rate; document.querySelectorAll("#speeds [data-r]").forEach((x) => x.classList.toggle("on", x === b)); }));
    document.querySelectorAll("[data-ph]").forEach((b) => (b.onclick = () => openPhrase(+b.dataset.ph)));
    document.querySelectorAll("[data-save]").forEach((b) => (b.onclick = () => savePhrase(+b.dataset.save)));
    const pa = document.getElementById("phrAll");
    if (pa) pa.onclick = async () => {
      busy(pa, true, "保存中"); const ks = (s.phrases || []).map((p, k) => k).filter((k) => !savedPhraseKeys().has(phraseKey(s.phrases[k].en)));
      try { for (const k of ks) await api("/api/phrases/save", { ep: epId, idx, i: k }); toast(`${ks.length}個のフレーズを保存しました`); } catch (err) { toast(err.message); }
      draw();
    };
    const prr = document.getElementById("phrRetry"); if (prr) prr.onclick = () => loadPhrases(true);
    document.querySelectorAll("[data-miss]").forEach((b) => (b.onclick = () => { const i = +b.dataset.miss; L.missed[i] = !L.missed[i]; draw(); }));
    document.querySelectorAll("[data-cause]").forEach((b) => (b.onclick = () => { L.cause[+b.dataset.li2] = b.dataset.cause; draw(); }));
    document.getElementById("jaBtn").onclick = async (e) => {
      if (L.showJa) { L.showJa = false; localSet("checkJa", false); draw(); return; }
      if (!s.lines.every((l) => l.ja)) {
        busy(e.currentTarget, true, "翻訳中");
        try { const r = await api("/api/translate", { ep: epId, idx }); s.lines = r.lines; }
        catch (err) { toast(err.message); busy(e.currentTarget, false); return; }
      }
      L.showJa = true; localSet("checkJa", true); draw();
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
  if (phrState === "loading") loadPhrases(false);
  // 日本語訳を初期表示：未翻訳の行があれば自動で取得
  const here = location.hash;
  if (L.showJa && !s.lines.every((l) => l.ja)) {
    const b = document.getElementById("jaBtn");
    if (b) busy(b, true, "翻訳中");
    try { const r = await api("/api/translate", { ep: epId, idx }); s.lines = r.lines; }
    catch (err) { toast(err.message); L.showJa = false; }
    if (location.hash === here) draw();
  }
};

// ================= 復習 =================
routes.review = async (mode) => {
  if (mode === "phr" || (!mode && !dueReviews().length && duePhrases().length)) return phraseReview();
  const items = dueReviews();
  let i = 0, shown = false;
  const draw = () => {
    if (i >= items.length) {
      $app.innerHTML = `<div class="stack" style="max-width:760px;margin:0 auto">${reviewTabs("lines")}<div class="card empty">${items.length ? "今日の聞き直しは完了です！" : "今日聞き直す文はありません。"}<br><br>${duePhrases().length ? `<a class="btn" href="#review/phr">フレーズの復習へ（${duePhrases().length}）</a>` : `<a class="btn" href="#home">ホームへ</a>`}</div></div>`;
      return;
    }
    const it = items[i]; const cause = CAUSES.find((c) => c.id === it.cause);
    const ep = S.episodes.find((e) => e.id === it.ep);
    $app.innerHTML = `<div class="stack" style="max-width:760px;margin:0 auto">
      ${reviewTabs("lines")}
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

