"use strict";
/* 記録・番組と音源 */
// ================= 記録 =================
routes.stats = async () => {
  try { talks = await api("/api/talks"); } catch (e) { talks = []; }
  const weeks = accuracyByWeek(6);
  const days = {}; S.progress.sessions.forEach((s) => (days[s.date] = (days[s.date] || 0) + 1));
  talks.forEach((t) => { const d = t.started.slice(0, 10); days[d] = (days[d] || 0) + 1; });
  const cal = []; const end = new Date(S.today + "T00:00:00");
  // 月曜始まりで直近4週＋今週
  const first = new Date(end); first.setDate(first.getDate() - ((end.getDay() + 6) % 7) - 21);
  for (let d = new Date(first); d <= end; d.setDate(d.getDate() + 1)) cal.push(days[ymd(d)] || 0);
  const now7 = causeCounts(7, 0), prev = causeCounts(35, 7);
  const tot = S.progress.sessions.length, totLines = S.progress.sessions.reduce((a, s) => a + (s.lines || 0), 0), totMiss = S.progress.sessions.reduce((a, s) => a + s.missed.length, 0);
  const maxV = Math.max(60, ...weeks.map((w) => w.val || 0));
  $app.innerHTML = `<div class="stack">
    <section class="stats">
      <div class="card stat"><div class="k">学習した区間</div><div class="v">${tot}<small>区間</small></div></div>
      <div class="card stat"><div class="k">聞き取れた文の割合（自己判定）</div><div class="v">${totLines ? Math.round(100 * (totLines - totMiss) / totLines) : "–"}<small>%</small></div></div>
      <div class="card stat"><div class="k">AIとの会話</div><div class="v">${talks.length}<small>回</small></div></div>
    </section>
    <section class="row">
      <div class="card grow stack"><div><h2 style="margin:0">要旨正答率（週ごと）</h2><p class="note">「内容が分かったか」の推移。まずは60%が目標</p></div>
        <div class="chart">${weeks.map((w) => `<div class="col"><span style="font-size:13px;font-weight:600">${w.val === null ? "–" : w.val + "%"}</span><div class="b ${w.now ? "now" : ""}" style="height:${w.val ? (w.val / maxV) * 160 : 2}px"></div></div>`).join("")}</div>
        <div class="labels">${weeks.map((w) => `<span>${w.label}</span>`).join("")}</div>
      </div>
      <div class="card side stack"><h2 style="margin:0">学習カレンダー</h2>
        <div class="cal">${["月", "火", "水", "木", "金", "土", "日"].map((d) => `<span class="small" style="text-align:center">${d}</span>`).join("")}
          ${cal.map((n) => `<div style="background:${n >= 2 ? "var(--blue)" : n === 1 ? "var(--blueMid)" : "var(--line2)"}" title="${n}"></div>`).join("")}</div>
        <div class="small" style="display:flex;gap:12px;flex-wrap:wrap"><span>■ 薄い：1回</span><span style="color:var(--blue)">■ 濃い：2回以上</span></div>
      </div>
    </section>
    <section class="card stack"><div><h2 style="margin:0">聞き取れなかった原因の変化</h2><p class="note">直近7日と、その前の4週間（1週あたり）の比較。減っている原因＝伸びたところ</p></div>
      ${CAUSES.map((c) => { const a = prev[c.id] / 4, b = now7[c.id]; const mx = Math.max(1, ...CAUSES.map((x) => Math.max(prev[x.id] / 4, now7[x.id])));
        const note = !a && !b ? "データなし" : b < a * 0.7 ? "改善" : b > a * 1.3 ? "増加" : "ほぼ横ばい";
        return `<div style="display:flex;flex-wrap:wrap;align-items:center;gap:12px"><span style="width:120px;font-weight:600;color:${c.color}">${c.label}</span>
        <div style="flex:1 1 300px;display:flex;flex-direction:column;gap:4px">
          <div style="display:flex;align-items:center;gap:8px"><span class="small" style="width:56px">以前</span><div class="bar" style="flex:1"><div style="width:${100 * a / mx}%;background:#CFCFC8"></div></div><span class="small" style="width:40px">${a.toFixed(1)}</span></div>
          <div style="display:flex;align-items:center;gap:8px"><span class="small" style="width:56px">直近7日</span><div class="bar" style="flex:1"><div style="width:${100 * b / mx}%;background:${c.color}"></div></div><span class="small" style="width:40px">${b}</span></div>
        </div><span style="width:90px;text-align:right;font-size:13px">${note}</span></div>`; }).join("")}
    </section></div>`;
};

// ================= 番組と音源・設定 =================
const STATUS = {
  new: ["未準備", "var(--sub)"], queued: ["順番待ち", "var(--orange)"], downloading: ["音声を取得中", "var(--orange)"],
  transcribing: ["文字起こし中", "var(--orange)"], generating: ["問題を作成中", "var(--orange)"], ready: ["準備完了", "var(--green)"], error: ["エラー", "var(--red)"],
};
routes.shows = async () => {
  const draw = () => {
    const c = S.config;
    const working = S.episodes.some((e) => ["queued", "downloading", "transcribing", "generating"].includes(e.status));
    $app.innerHTML = `<div class="row">
      <div class="grow stack">
        <section class="card"><label class="lbl" for="feed">ポッドキャストを登録</label>
          <div class="field"><input id="feed" type="text" placeholder="Apple Podcasts のURL または RSSフィードのURL"><button class="btn" id="addFeed" style="border-radius:10px">登録</button></div>
          <p class="note" style="margin-top:8px">URLを貼るだけでRSSを自動で探します。Spotify限定の番組は登録できません</p></section>
        ${c.feeds.map((f) => { const eps = S.episodes.filter((e) => e.feed_id === f.id && e.status !== "deleted").slice(0, 10); return `<section class="card">
          <div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px">
            <div><div style="font-size:16px;font-weight:700">${esc(f.title)}</div><div class="small">最終チェック ${esc((f.last_check || "").replace("T", " ").slice(0, 16))}${f.last_error ? ` ・ <span style="color:var(--red)">${esc(f.last_error)}</span>` : ""}</div></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="chip ${f.auto ? "on" : ""}" data-auto="${f.id}">夜間の自動準備 ${f.auto ? "ON" : "OFF"}</button>
            <button class="chip" data-rmfeed="${f.id}" style="color:var(--red)">番組を削除</button></div>
          </div>
          <div class="list" style="margin-top:8px">${eps.map((e) => { const st = STATUS[e.status] || STATUS.new; const act = ["queued", "downloading", "transcribing", "generating"].includes(e.status); return `<div class="item">
            <div style="flex:1 1 280px;min-width:0"><div style="font-weight:600">${esc(e.title)}</div>
              <div class="small">${e.published_ts ? new Date(e.published_ts * 1000).toLocaleDateString("ja-JP") : ""} ${e.duration_text ? "・ " + esc(e.duration_text) : ""} ${e.sections ? `・ ${e.sections}区間` : ""}</div>
              ${e.message ? `<div class="small" style="color:${e.status === "error" ? "var(--red)" : "var(--sub)"}">${esc(e.message)}</div>` : ""}</div>
            <div style="flex:0 1 200px;display:flex;flex-direction:column;gap:4px">
              <span style="font-size:12px;font-weight:700;color:${st[1]}">${act ? '<span class="spin"></span> ' : ""}${st[0]}${act && e.progress ? ` ${e.progress}%` : ""}</span>
              ${act ? `<div class="bar" style="height:6px"><div style="width:${e.progress || 0}%;background:${st[1]}"></div></div>` : ""}
            </div>
            ${e.status === "ready" && !e.audio_size ? `<button class="btn sm ghost" data-prep="${e.id}" title="広告で音声と文字がずれるため、音声を保存して作り直します">音声を保存して作り直す</button>`
              : e.status === "ready" && e.timing !== "word" ? `<button class="btn sm ghost" data-redo="${e.id}" title="1文ずつ再生したとき次の文まで流れないよう、文の区切りを単語単位で取り直します">区切りを正確にして作り直す</button>` : ""}
            ${e.status === "ready" ? `<a class="btn sm" href="#listen/${e.id}/0">聞く</a><button class="btn plain sm" data-regen="${e.id}" title="要旨問題と表現を作り直す">問題を作り直す</button>`
              : act ? `<button class="btn plain sm" data-cancel="${e.id}">中断</button>` : `<button class="btn sm ghost" data-prep="${e.id}">${e.status === "error" ? "再試行" : "準備する"}</button>`}
            <button class="btn plain sm" data-rmep="${e.id}" title="この回を一覧から消し、保存した音声・文字起こしも削除">削除</button>
          </div>`; }).join("") || '<div class="empty">エピソードがありません</div>'}</div>
          <p class="small" style="margin-top:8px">準備の流れ：「準備する」→ 30分以内にGitHub Actionsが文字起こし（Whisper・無料）→ 区間分割 → 要旨問題・表現の作成（Gemini）</p>
        </section>`; }).join("")}
        ${c.feeds.length ? `<div><button class="btn plain sm" id="check">新着を今すぐ確認</button></div>` : ""}
        <section class="card"><div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><label class="lbl" for="yt" style="margin:0">YouTube動画を追加</label><span class="pill" style="background:#F0F0EC;color:var(--sub)">聞くだけモード</span></div>
          <div class="field"><input id="yt" type="text" placeholder="YouTube動画のURL"><input id="ytt" type="text" placeholder="メモ（任意）" style="flex:0 1 200px"><button class="btn ghost" id="addYt" style="border-radius:10px">追加</button></div>
          <p class="note" style="margin-top:8px">ツール内の埋め込みプレーヤーで再生。区間リピート・速度変更は使えますが、文字起こしと答え合わせはありません</p>
          ${c.youtube.length ? `<div class="list" style="margin-top:8px">${c.youtube.map((y) => `<div class="item"><a href="#yt/${y.id}" style="flex:1">${esc(y.title)}</a><span class="small">${esc(y.added)}</span><button class="btn plain sm" data-rmyt="${y.id}">削除</button></div>`).join("")}</div>` : ""}
        </section>
      </div>
      <aside class="card side stack" style="gap:18px">
        <h2 style="margin:0">設定</h2>
        <div><label class="lbl" for="key" style="font-size:13px">Gemini APIキー（無料）</label>
          <div class="small" style="margin-bottom:6px">${c.has_key ? `設定済み（${esc(c.key_hint)}）${c.gemini_model ? ` ・ ${esc(c.gemini_model)}` : ""}` : `<a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio</a>で無料で発行できます`}</div>
          ${c.cloud ? `<p class="small">キーはRenderの環境変数 GEMINI_API_KEY に設定します（GitHub ActionsのSecretsにも同じキー）</p>` : `<div class="field"><input id="key" type="password" placeholder="${c.has_key ? "変更する場合のみ入力" : "APIキーを貼り付け"}" autocomplete="off"><button class="btn sm" id="saveKey">保存</button></div>`}
          ${c.has_key ? `<button class="btn plain sm" id="testKey" style="margin-top:8px">接続テスト</button>` : ""}
          <p class="small" style="margin-top:6px">無料枠では会話内容がGoogleのサービス改善に使われることがあります。個人情報は話さないでください。</p></div>
        <div><span class="lbl" style="font-size:13px">区間の長さ</span><div style="display:flex;gap:6px">${[3, 4, 5].map((m) => `<button class="chip ${c.segment_minutes === m ? "on" : ""}" data-len="${m}" style="flex:1;justify-content:center">${m}分</button>`).join("")}</div>
          <p class="small" style="margin-top:4px">次に準備するエピソードから反映</p></div>
        <div><span class="lbl" style="font-size:13px">文字起こしの精度（無料）</span>
          ${[["base.en", "速さ優先", "精度はふつう"], ["small.en", "精度優先（おすすめ）", "GitHub Actionsで処理するので時間は気にならない"]].map(([id, l, n]) => `<button class="choice ${c.whisper_model === id ? "on" : ""}" data-wm="${id}" style="margin-bottom:6px"><div style="font-weight:600">${l}</div><div class="small">${n}</div></button>`).join("")}</div>
        <div><span class="lbl" style="font-size:13px">夜間の自動準備</span><button class="chip ${c.auto_prepare ? "on" : ""}" id="autoAll">${c.auto_prepare ? "ON" : "OFF"}</button>
          <p class="small" style="margin-top:4px">毎朝3時ごろ、新着（または未準備の最新回）を1本ずつ準備します（GitHub Actions）</p></div>
      </aside></div>`;
    bind();
    clearInterval(pollTimer);
    if (working) pollTimer = setInterval(async () => { await refresh(); if (location.hash.startsWith("#shows") && !document.activeElement.matches("input")) draw(); }, 4000);
  };
  const bind = () => {
    const act = async (btn, fn, label) => { busy(btn, true, label); try { await fn(); draw(); } catch (e) { toast(e.message, 6000); busy(btn, false); } };
    document.getElementById("addFeed").onclick = (e) => act(e.currentTarget, async () => { const v = document.getElementById("feed").value; if (!v.trim()) throw new Error("URLを入力してください"); await api("/api/feeds", { url: v }); toast("登録しました。エピソードの「準備する」を押してください"); }, "確認中");
    const ck = document.getElementById("check"); if (ck) ck.onclick = (e) => act(e.currentTarget, () => api("/api/feeds/check", {}), "確認中");
    document.querySelectorAll("[data-auto]").forEach((b) => (b.onclick = () => act(b, () => api("/api/feeds/toggle", { id: b.dataset.auto }))));
    document.querySelectorAll("[data-prep]").forEach((b) => (b.onclick = () => act(b, () => api("/api/episodes/prepare", { id: b.dataset.prep }))));
    document.querySelectorAll("[data-redo]").forEach((b) => (b.onclick = () => act(b, () => api("/api/episodes/prepare", { id: b.dataset.redo, redo: true }))));
    document.querySelectorAll("[data-cancel]").forEach((b) => (b.onclick = () => act(b, () => api("/api/episodes/cancel", { id: b.dataset.cancel }), "中断中")));
    document.querySelectorAll("[data-regen]").forEach((b) => (b.onclick = () => act(b, () => api("/api/episodes/regenerate", { id: b.dataset.regen }))));
    document.getElementById("addYt").onclick = (e) => act(e.currentTarget, () => api("/api/youtube", { url: document.getElementById("yt").value, title: document.getElementById("ytt").value }));
    document.querySelectorAll("[data-rmep]").forEach((b) => (b.onclick = () => act(b, () => api("/api/episodes/delete", { id: b.dataset.rmep }), "削除中")));
    document.querySelectorAll("[data-rmfeed]").forEach((b) => (b.onclick = () => { if (confirm("この番組と、すべての回（音声・文字起こし・復習の文）を削除しますか？")) act(b, () => api("/api/feeds/delete", { id: b.dataset.rmfeed }), "削除中"); }));
    document.querySelectorAll("[data-rmyt]").forEach((b) => (b.onclick = () => act(b, () => api("/api/youtube/remove", { id: b.dataset.rmyt }))));
    const sk = document.getElementById("saveKey"); if (sk) sk.onclick = (e) => act(e.currentTarget, async () => { const v = document.getElementById("key").value.trim(); if (!v) throw new Error("APIキーを入力してください"); await api("/api/settings", { gemini_api_key: v }); const r = await api("/api/test-key", {}); await refresh(); toast(`接続OK（${r.model}）`); }, "確認中");
    const tk = document.getElementById("testKey"); if (tk) tk.onclick = (e) => act(e.currentTarget, async () => { const r = await api("/api/test-key", {}); await refresh(); toast(`接続OK（${r.model}）`); }, "確認中");
    document.querySelectorAll("[data-len]").forEach((b) => (b.onclick = () => act(b, () => api("/api/settings", { segment_minutes: +b.dataset.len }))));
    document.querySelectorAll("[data-wm]").forEach((b) => (b.onclick = () => act(b, () => api("/api/settings", { whisper_model: b.dataset.wm }))));
    document.getElementById("autoAll").onclick = (e) => act(e.currentTarget, () => api("/api/settings", { auto_prepare: !S.config.auto_prepare }));
  };
  await refresh();
  draw();
};

