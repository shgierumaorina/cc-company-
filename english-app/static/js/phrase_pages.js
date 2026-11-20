"use strict";
/* 日常会話フレーズ：復習・フレーズ帳・ロールプレイ */
// ================= フレーズ復習 =================
function reviewTabs(cur) {
  const n1 = dueReviews().length, n2 = duePhrases().length;
  return `<div class="segtabs">
    <a href="#review/lines" class="${cur === "lines" ? "on" : ""}">聞き直し<span class="cnt">${n1}</span></a>
    <a href="#review/phr" class="${cur === "phr" ? "on" : ""}">フレーズ<span class="cnt phr">${n2}</span></a>
    <a href="#phrases" class="${cur === "book" ? "on" : ""}">フレーズ帳</a></div>`;
}
const PHR_MODES = [
  { min: 0, label: "① 聞いて意味をつかむ", ok: "わかった", ng: "まだ" },
  { min: 2, label: "② 日本語から英語で言う", ok: "言えた", ng: "まだ" },
  { min: 4, label: "③ 場面から自分で言う", ok: "言えた", ng: "まだ" },
];
const phrMode = (p) => (p.stage || 0) >= 4 ? 2 : (p.stage || 0) >= 2 ? 1 : 0;
async function phraseReview() {
  const items = duePhrases().sort((a, b) => (a.due < b.due ? -1 : 1));
  let i = 0, shown = false, said = "", listening = false;
  const draw = () => {
    if (i >= items.length) {
      $app.innerHTML = `<div class="stack" style="max-width:760px;margin:0 auto">${reviewTabs("phr")}<div class="card empty">${items.length ? "今日のフレーズ復習は完了です！" : "今日復習するフレーズはありません。"}<br>
        <span class="small">答え合わせ画面の「日常会話フレーズ」で保存すると、ここに出てきます</span><br><br>
        ${(S.progress.phrases || []).length ? `<a class="btn" href="#roleplay">保存したフレーズで会話練習</a>` : `<a class="btn" href="#home">ホームへ</a>`}</div></div>`;
      return;
    }
    const p = items[i]; const m = phrMode(p); const M = PHR_MODES[m];
    const hasAudio = p.start !== null && p.start !== undefined;
    const sc = said ? matchScore(said, [p.en, ...(p.alts || []).map((a) => a.en)]) : null;
    let prompt = "";
    if (m === 0) prompt = `<p class="note">音声を聞いて、意味が分かるか確かめましょう</p>
      <div class="controls">${hasAudio ? `<button class="round" id="orig" aria-label="原音を再生">${ICON.play}</button>` : ""}
        <button class="chip" id="tts">${ICON.speaker}フレーズだけ</button>${hasAudio ? `<button class="chip" id="slow">0.75xで原音</button>` : ""}</div>`;
    else if (m === 1) prompt = `<div class="pr-q">${esc(p.ja)}</div>${p.scene_ja ? `<div class="note">場面：${esc(p.scene_ja)}</div>` : ""}<p class="note">英語で声に出して言ってみましょう</p>`;
    else prompt = `<div class="pr-q">${esc(p.task_ja || `${p.scene_ja}。「${p.ja}」と言いたい`)}</div><p class="note">自分の言葉で英語にしてみましょう。言い換えでもOK</p>`;
    $app.innerHTML = `<div class="stack" style="max-width:760px;margin:0 auto">
      ${reviewTabs("phr")}
      <div class="small">フレーズ ${i + 1} / ${items.length} ・ <b style="color:var(--purple)">${M.label}</b> ・ 段階 ${(p.stage || 0) + 1}/5</div>
      <section class="card stack" style="align-items:center;text-align:center">
        ${prompt}
        ${m > 0 ? `<div class="live" id="said" style="text-align:left">${said ? esc(said) : '<span class="small">マイクを押して話す（話し終えると自動で止まります）</span>'}</div>
          <button class="mic ${listening ? "rec" : ""}" id="pmic" aria-label="話す">${ICON.mic}</button>
          ${sc ? `<div class="score ${sc.pct >= 80 ? "ok" : ""}">一致度 ${sc.pct}%${sc.miss.length && sc.pct < 100 ? `<span class="small">　足りない語：${esc(sc.miss.join(", "))}</span>` : ""}</div>` : ""}` : ""}
        <div class="pr-ans">
          ${shown ? `<div class="pr-en">${esc(p.en)} ${regPill(p.register)}</div><div>${esc(p.ja)}</div>
            <div class="controls" style="gap:8px">${ttsBtn(p.en, "読み上げ")}${hasAudio && m > 0 ? `<button class="chip sm" id="orig2">${ICON.play}原音</button>` : ""}</div>
            <div class="pd" style="text-align:left">${phraseDetailHtml(p)}</div>` : `<button class="btn plain" id="show">答えを見る</button>`}
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:center">
          <button class="btn ghost" id="ng">${M.ng}</button>
          <button class="btn" id="ok">${M.ok}</button>
        </div>
      </section></div>`;
    const orig = (r) => hasAudio && playRange(`/audio/${p.ep}`, Math.max(0, p.start - 0.15), p.end + 0.2, r || 1, true);
    const g = (id) => document.getElementById(id);
    if (g("orig")) g("orig").onclick = () => orig(1);
    if (g("slow")) g("slow").onclick = () => orig(0.75);
    if (g("orig2")) g("orig2").onclick = () => orig(1);
    if (g("tts")) g("tts").onclick = () => speak(p.en);
    if (g("show")) g("show").onclick = () => { shown = true; draw(); };
    if (g("pmic")) g("pmic").onclick = () => {
      if (listening) { stopRec(); listening = false; draw(); return; }
      const ok = listenOnce((t) => { const el = g("said"); if (el) el.textContent = t; }, (t) => { listening = false; said = t || said; if (location.hash.startsWith("#review/phr")) draw(); });
      if (ok) { listening = true; said = ""; draw(); }
    };
    bindTts();
    const ans = async (ok) => { stopRec(); try { await api("/api/phrases/answer", { id: p.id, ok }); } catch (e) { toast(e.message); } i++; shown = false; said = ""; listening = false; draw(); };
    g("ok").onclick = () => ans(true);
    g("ng").onclick = () => ans(false);
    if (m === 0 && !shown) { if (hasAudio) orig(1); else speak(p.en); }
  };
  draw();
}

// ================= フレーズ帳 =================
routes.phrases = async () => {
  const all = [...(S.progress.phrases || [])].sort((a, b) => (a.done ? 1 : 0) - (b.done ? 1 : 0) || (a.due < b.due ? -1 : a.due > b.due ? 1 : 0));
  const due = duePhrases().length, used = all.filter((p) => p.used_count).length;
  $app.innerHTML = `<div class="stack" style="max-width:860px;margin:0 auto">
    ${reviewTabs("book")}
    <section class="stats">
      <div class="card stat"><div class="k">保存したフレーズ</div><div class="v">${all.length}<small>個</small></div></div>
      <div class="card stat"><div class="k">今日の復習</div><div class="v">${due}<small>個</small></div>${due ? `<a href="#review/phr" class="small">復習する →</a>` : ""}</div>
      <div class="card stat"><div class="k">会話で使えた</div><div class="v">${used}<small>個</small></div></div>
    </section>
    ${all.length ? `<a class="btn" href="#roleplay">${ICON.chat} 保存したフレーズでロールプレイ</a>` : ""}
    <section class="card"><h2>フレーズ帳</h2>
      ${all.map((p) => { const st = p.done ? "定着" : `段階 ${(p.stage || 0) + 1}/5`; const dueNow = !p.done && p.due <= S.today;
        return `<details class="pb"><summary><div style="flex:1 1 220px;min-width:0"><div class="phr-en">${esc(p.en)}</div><div class="chk-ja">${esc(p.ja)}</div></div>
          <div class="pb-meta">${regPill(p.register)}<span class="small">${st}${dueNow ? " ・ <b style='color:var(--purple)'>今日</b>" : p.done ? "" : ` ・ 次 ${esc(p.due.slice(5).replace("-", "/"))}`}</span>${p.used_count ? `<span class="small" style="color:var(--green)">会話で${p.used_count}回</span>` : ""}</div></summary>
          <div class="pd">${phraseDetailHtml(p)}
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px">${ttsBtn(p.en, "読み上げ")}${p.start !== null && p.start !== undefined ? `<button class="chip sm" data-orig="${p.id}">${ICON.play}原音</button>` : ""}
            <a class="chip sm" href="#listen/${p.ep}/${p.idx}">元の区間</a><button class="chip sm del" data-del="${p.id}">削除</button></div></div></details>`; }).join("") || '<p class="note">まだありません。答え合わせ画面の「日常会話フレーズ」から保存できます。</p>'}
    </section></div>`;
  bindTts();
  document.querySelectorAll("[data-orig]").forEach((b) => (b.onclick = () => { const p = all.find((x) => x.id === b.dataset.orig); playRange(`/audio/${p.ep}`, Math.max(0, p.start - 0.15), p.end + 0.2, 1); }));
  document.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { if (!confirm("このフレーズを削除しますか？")) return; await api("/api/phrases/remove", { id: b.dataset.del }); routes.phrases(); }));
};

// ================= ロールプレイ（保存したフレーズを会話で使う） =================
const SCENES = [["auto", "おまかせ"], ["cafe", "カフェ・レストラン"], ["work", "職場の雑談"], ["friend", "友達と予定を立てる"], ["shop", "買い物"], ["street", "道を聞く・教える"], ["meeting", "オンライン会議"]];
routes.roleplay = async () => {
  const all = S.progress.phrases || [];
  if (!all.length) {
    $app.innerHTML = `<div class="card empty" style="max-width:720px;margin:0 auto">まだフレーズが保存されていません。<br>答え合わせ画面の「日常会話フレーズ」で保存すると、ここで会話練習できます。<br><br><a class="btn" href="#theme">会話テーマへ</a></div>`;
    return;
  }
  // 優先：復習日が来たもの → 会話でまだ使っていないもの → 新しいもの
  const cands = [...all].sort((a, b) => (a.done ? 1 : 0) - (b.done ? 1 : 0) || ((a.due <= S.today ? 0 : 1) - (b.due <= S.today ? 0 : 1)) || ((a.used_count || 0) - (b.used_count || 0)) || (a.added < b.added ? 1 : -1)).slice(0, 12);
  let picked = new Set(cands.slice(0, 3).map((p) => p.id)), scene = localGet("scene", "auto");
  const draw = () => {
    $app.innerHTML = `<div class="stack" style="max-width:820px;margin:0 auto">
      <div class="small"><a href="#theme">← 会話テーマ</a> ・ ロールプレイ</div>
      <section class="card stack"><div><h2 style="margin:0">使うフレーズ（最大4つ）</h2><p class="note">AIが、これらを言いたくなる場面を作ります</p></div>
        <div class="stack" style="gap:8px">${cands.map((p) => `<button class="choice rp ${picked.has(p.id) ? "on" : ""}" data-pk="${p.id}">
          <span class="ck">${picked.has(p.id) ? "✓" : ""}</span><span style="flex:1;min-width:0"><span class="phr-en" style="display:block">${esc(p.en)}</span><span class="small">${esc(p.ja)}${p.used_count ? ` ・ 会話で${p.used_count}回` : ""}</span></span></button>`).join("")}</div></section>
      <section class="card stack"><h2 style="margin:0">場面</h2>
        <div style="display:flex;flex-wrap:wrap;gap:8px">${SCENES.map(([k, l]) => `<button class="chip ${scene === k ? "on" : ""}" data-sc="${k}">${l}</button>`).join("")}</div></section>
      <button class="btn" id="go" ${picked.size ? "" : "disabled"}>この${picked.size}つで会話を始める</button>
    </div>`;
    document.querySelectorAll("[data-pk]").forEach((b) => (b.onclick = () => {
      const id = b.dataset.pk;
      if (picked.has(id)) picked.delete(id); else if (picked.size >= 4) { toast("選べるのは4つまでです"); return; } else picked.add(id);
      draw();
    }));
    document.querySelectorAll("[data-sc]").forEach((b) => (b.onclick = () => { scene = b.dataset.sc; localSet("scene", scene); draw(); }));
    document.getElementById("go").onclick = async (e) => {
      busy(e.currentTarget, true, "場面を準備中");
      try { const t = await api("/api/talk/start", { mode: "roleplay", phrase_ids: [...picked], scene }); go(`talk/${t.id}`); }
      catch (err) { toast(err.message, 6000); busy(e.currentTarget, false); }
    };
  };
  draw();
};
