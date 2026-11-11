"use strict";
/* ホーム・区間を聞く */
// ================= ホーム =================
routes.home = async () => {
  try { talks = await api("/api/talks"); } catch (e) { talks = []; }
  const cfg = S.config;
  if (!cfg.has_key || !cfg.feeds.length) {
    $app.innerHTML = `<div class="stack">
      <div class="card"><h2>はじめに</h2>
        <ol style="margin:0;padding-left:20px;line-height:2">
          <li ${cfg.has_key ? 'style="color:var(--green)"' : ""}>GeminiのAPIキー（無料）を設定する ${cfg.has_key ? "✓" : ""}</li>
          <li ${cfg.feeds.length ? 'style="color:var(--green)"' : ""}>聞きたいポッドキャストを登録する ${cfg.feeds.length ? "✓" : ""}</li>
          <li>エピソードの「準備する」を押す（文字起こしに数十分かかります）</li>
        </ol>
        <p style="margin-top:16px"><a class="btn" href="#shows">設定と番組の登録へ</a></p>
      </div></div>`;
    return;
  }
  const next = nextSection();
  const acc = accuracyByWeek(2);
  const due = dueReviews().length;
  const c7 = causeCounts(7, 0); const maxC = Math.max(1, ...Object.values(c7));
  const ep = next ? next.ep : readyEps()[0];
  let sections = [];
  if (ep) sections = (await api(`/api/episode/${ep.id}`)).sections;
  const done = doneSet();
  const working = S.episodes.filter((e) => ["queued", "downloading", "transcribing", "generating"].includes(e.status));

  $app.innerHTML = `<div class="stack">
    <section class="stats">
      <div class="card stat"><div class="k">連続学習</div><div class="v">${streak()}<small>日</small></div></div>
      <div class="card stat"><div class="k">今週の要旨正答率</div><div class="v">${acc[1].val ?? "–"}<small>%</small></div>
        <div class="up">${acc[0].val !== null && acc[1].val !== null ? `先週 ${acc[0].val}% → ${acc[1].val - acc[0].val >= 0 ? "+" : ""}${acc[1].val - acc[0].val}pt` : `今週 ${acc[1].n}区間`}</div></div>
      <div class="card stat"><div class="k">復習待ちの文</div><div class="v">${due}<small>文</small></div>${due ? `<a href="#review" class="small">復習する →</a>` : ""}</div>
    </section>
    ${next ? `<section class="hero">
      <div style="display:flex;flex-direction:column;gap:6px;min-width:0;flex:1 1 380px">
        <div class="s">今日のメニュー（約10分）</div>
        <div class="t">${esc(next.ep.title)}</div>
        <div class="s">${esc(next.ep.show || "")} ・ 区間 ${next.idx + 1} / ${next.ep.sections}</div>
      </div>
      <a class="btn white" href="#listen/${next.ep.id}/${next.idx}">${ICON.play} 今日の区間を始める</a>
    </section>` : `<section class="card empty">${working.length ? `<span class="spin"></span> 「${esc(working[0].title)}」を準備中です（${esc(working[0].message || "")} ${working[0].progress || 0}%）` : `準備済みの区間がありません。<a href="#shows">番組と音源</a>でエピソードを「準備」してください`}</section>`}
    <section class="row">
      <div class="card grow"><h2>区間一覧${ep ? `：${esc(ep.title)}` : ""}</h2>
        <div class="list">${sections.map((s) => {
          const isDone = done.has(`${ep.id}:${s.index}`); const isNext = next && next.ep.id === ep.id && next.idx === s.index;
          const st = isDone ? ["完了", "var(--greenSoft)", "var(--green)"] : isNext ? ["今日", "var(--blueSoft)", "var(--blue)"] : ["未着手", "#F0F0EC", "var(--sub)"];
          return `<div class="item"><span style="width:26px;color:var(--sub)">${s.index + 1}</span><span class="tm" style="width:110px;color:var(--sub);font-size:14px">${fmt(s.start)}–${fmt(s.end)}</span>
            <a href="#listen/${ep.id}/${s.index}" style="flex:1;min-width:0;color:var(--ink);text-decoration:none">${esc(s.topic_ja || "（話題未作成）")}</a>
            <span class="pill" style="background:${st[1]};color:${st[2]}">${st[0]}</span></div>`;
        }).join("") || '<div class="empty">まだありません</div>'}</div>
      </div>
      <aside class="card side stack" style="gap:14px"><h2 style="margin:0">今の弱点</h2>
        <p class="note">聞き取れなかった文の原因（直近7日）</p>
        ${CAUSES.map((c) => `<div style="display:flex;flex-direction:column;gap:6px">
          <div style="display:flex;justify-content:space-between;font-size:14px"><span>${c.label}</span><b>${c7[c.id]}文</b></div>
          <div class="bar"><div style="width:${Math.round(100 * c7[c.id] / maxC)}%;background:${c.color}"></div></div></div>`).join("")}
        <a href="#stats" style="font-size:14px">詳しく見る →</a>
      </aside>
    </section></div>`;
  if (working.length) pollTimer = setInterval(async () => { await refresh(); if (!S.episodes.some((e) => ["queued", "downloading", "transcribing", "generating"].includes(e.status))) render(); }, 5000);
};

// ================= 区間を聞く =================
let L = null; // 現在の学習状態
routes.listen = async (epId, idx) => {
  idx = +idx;
  const d = await api(`/api/episode/${epId}`);
  const s = d.sections[idx];
  if (!s) { go("home"); return; }
  if (!L || L.ep !== epId || L.idx !== idx) L = { ep: epId, idx, choice: null, feel: null, missed: {}, cause: {}, rate: 1, showJa: false };
  const src = `/audio/${epId}`;
  const choices = [...(s.choices || []), "よくわからなかった"];
  $app.innerHTML = `<div class="stack" style="max-width:880px;margin:0 auto">
    <div class="small"><a href="#home">← ホーム</a> ・ 区間 ${idx + 1} / ${d.sections.length} ・ ステップ 1/2 聞く</div>
    <section class="card player">
      <div><div class="small">${esc(d.meta.show || "")}</div><h1 style="margin:4px 0 0;font-size:21px">${esc(d.meta.title)}</h1></div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <div class="bar" id="pbar" style="cursor:pointer"><div id="pfill" style="width:0;background:var(--blue)"></div></div>
        <div style="display:flex;justify-content:space-between" class="small"><span id="ptime">${fmt(s.start)}</span><span>この区間 ${fmt(s.start)}–${fmt(s.end)}</span></div>
      </div>
      <div class="controls">
        <button class="chip" id="back5">${ICON.back}5秒戻る</button>
        <button class="round" id="pp" aria-label="再生">${ICON.play}</button>
        <button class="chip ${L.loop ? "on" : ""}" id="rep">${ICON.repeat}区間リピート</button>
      </div>
      <div class="controls" id="speeds">${[0.75, 0.9, 1, 1.25].map((r) => `<button class="chip ${L.rate === r ? "on" : ""}" data-r="${r}">${r}x</button>`).join("")}</div>
      <p class="note" style="text-align:center">まずは字幕なしで。わからなくても止めずに最後まで</p>
    </section>
    <section class="card stack">
      <div style="font-size:13px;font-weight:700;color:var(--blue)">要旨チェック</div>
      <h2 style="margin:0;font-size:18px">この区間では主に何について話していましたか？</h2>
      ${s.choices && s.choices.length ? `<div class="choices">${choices.map((c, i) => `<button class="choice ${L.choice === i ? "on" : ""}" data-c="${i}">${String.fromCharCode(65 + i)}. ${esc(c)}</button>`).join("")}</div>`
        : `<p class="note">この区間の要旨問題はまだ作成されていません（番組と音源の画面で「問題を作り直す」）。</p>`}
      <div><div style="font-weight:600;font-size:14px;margin-bottom:8px">体感でどのくらい聞き取れた？</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">${["ほぼ全部", "半分くらい", "3割くらい", "ほとんど無理"].map((f) => `<button class="chip ${L.feel === f ? "on" : ""}" data-f="${esc(f)}">${f}</button>`).join("")}</div></div>
      <div style="display:flex;justify-content:flex-end"><button class="btn" id="toCheck">答え合わせへ →</button></div>
    </section></div>`;

  const pp = document.getElementById("pp");
  onTick = () => {
    const t = player.currentTime; const pct = Math.min(100, Math.max(0, 100 * (t - s.start) / (s.end - s.start)));
    document.getElementById("pfill").style.width = pct + "%";
    document.getElementById("ptime").textContent = fmt(t);
    pp.innerHTML = player.paused ? ICON.play : ICON.pause; pp.setAttribute("aria-label", player.paused ? "再生" : "一時停止");
  };
  player.src = src; player.playbackRate = L.rate;
  mediaSession(d.meta.title, `${d.meta.show || ""} ・ 区間 ${idx + 1}`, {
    play: () => { if (player.paused) pp.click(); },
    pause: () => player.pause(),
    seekbackward: () => { player.currentTime = Math.max(s.start, player.currentTime - 5); },
    previoustrack: () => { player.currentTime = s.start; },
  });
  pp.onclick = () => {
    if (!player.paused) { player.pause(); return; }
    const t = player.currentTime; const from = t >= s.start && t < s.end - 0.5 ? t : s.start;
    playRange(src, from, s.end, L.rate); loop = L.loop ? s.start : null;
  };
  document.getElementById("back5").onclick = () => { player.currentTime = Math.max(s.start, player.currentTime - 5); };
  document.getElementById("rep").onclick = (e) => { L.loop = !L.loop; e.currentTarget.classList.toggle("on", L.loop); loop = L.loop && !player.paused ? s.start : null; };
  document.getElementById("pbar").onclick = (e) => { const r = e.currentTarget.getBoundingClientRect(); player.currentTime = s.start + (s.end - s.start) * (e.clientX - r.left) / r.width; };
  document.querySelectorAll("#speeds [data-r]").forEach((b) => (b.onclick = () => { L.rate = +b.dataset.r; player.playbackRate = L.rate; document.querySelectorAll("#speeds [data-r]").forEach((x) => x.classList.toggle("on", x === b)); }));
  document.querySelectorAll("[data-c]").forEach((b) => (b.onclick = () => { L.choice = +b.dataset.c; document.querySelectorAll("[data-c]").forEach((x) => x.classList.toggle("on", x === b)); }));
  document.querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => { L.feel = b.dataset.f; document.querySelectorAll("[data-f]").forEach((x) => x.classList.toggle("on", x === b)); }));
  document.getElementById("toCheck").onclick = () => {
    if (s.choices && s.choices.length && L.choice === null) { toast("先に要旨の選択肢を選んでください"); return; }
    go(`check/${epId}/${idx}`);
  };
};

