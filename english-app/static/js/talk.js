"use strict";
/* 会話テーマ・会話 */
// ================= 会話テーマ =================
routes.theme = async (epId, idx) => {
  let segTheme = null;
  if (epId) {
    const d = await api(`/api/episode/${epId}`); const s = d.sections[+idx];
    if (s) segTheme = { name: s.topic_ja || s.summary_ja || "聞いた区間の話題", detail: s.summary_ja, targets: s.chunks || [], ep: epId, idx: +idx };
  }
  if (!segTheme) {
    const done = [...S.progress.sessions].reverse()[0];
    if (done) {
      try { const d = await api(`/api/episode/${done.ep}`); const s = d.sections[done.idx]; if (s) segTheme = { name: s.topic_ja || "最近聞いた区間の話題", detail: s.summary_ja, targets: s.chunks || [] }; } catch (e) { /* noop */ }
    }
  }
  let sel = segTheme ? "seg" : (S.progress.themes[0] || {}).id;
  const draw = () => {
    const themes = S.progress.themes;
    const cur = sel === "seg" ? segTheme : themes.find((t) => t.id === sel);
    $app.innerHTML = `<div class="row">
      <div class="grow stack">
        <section class="card"><label class="lbl" for="nt">テーマを追加</label>
          <div class="field"><input id="nt" type="text" placeholder="例：週末の過ごし方 / my morning routine"><button class="btn" id="add" style="border-radius:10px">追加</button></div>
          <p class="note" style="margin-top:8px">日本語でも英語でもOK。AIが最初の質問と使えそうな表現を用意します</p></section>
        ${segTheme ? `<section><h2 style="font-size:15px;margin:0 0 10px">ポッドキャストから</h2>
          <button class="choice ${sel === "seg" ? "on" : ""}" id="seg"><div style="font-size:12px;font-weight:700;color:var(--blue)">おすすめ ・ 聞いた区間の話題</div><div style="font-weight:600;font-size:16px">${esc(segTheme.name)}</div></button></section>` : ""}
        <section><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:8px;flex-wrap:wrap"><h2 style="font-size:15px;margin:0">自分のテーマ</h2><button class="chip" id="rand">おまかせ</button></div>
          <div class="themes">${[...themes].sort((a, b) => (b.fav ? 1 : 0) - (a.fav ? 1 : 0)).map((t) => `<div class="theme ${sel === t.id ? "on" : ""}">
            <button class="pick" data-t="${t.id}"><span style="font-weight:600">${esc(t.name)}</span><span class="small">${t.count ? `${t.count}回 ・ 最終 ${esc(t.last || "")}` : "未実施"}</span></button>
            <button class="star ${t.fav ? "on" : ""}" data-fav="${t.id}" aria-label="お気に入り">${ICON.star.replace("FILL", t.fav ? "#F2B54A" : "none")}</button>
          </div>`).join("")}</div></section>
        ${talks.length ? `<section class="card"><h2>最近の会話</h2><div class="list">${talks.slice(0, 8).map((t) => `<div class="item"><a href="#talk/${t.id}" style="flex:1">${esc(t.theme)}</a><span class="small">${esc(t.started.slice(0, 16).replace("T", " "))} ・ ${t.turns}往復</span><button class="btn plain sm" data-rmtalk="${t.id}">削除</button></div>`).join("")}</div></section>` : ""}
      </div>
      <aside class="card side stack">
        <div style="font-size:12px;font-weight:700;color:var(--blue)">選択中のテーマ</div>
        <div style="font-size:18px;font-weight:700">${esc(cur ? cur.name : "（テーマを選んでください）")}</div>
        ${cur && cur.targets && cur.targets.length ? `<div><div class="small" style="margin-bottom:6px">使ってみたい表現</div><div style="display:flex;flex-wrap:wrap;gap:6px">${cur.targets.map((x) => `<span class="pill" style="background:var(--purpleSoft);color:var(--purpleInk);font-size:13px">${esc(x.en)}</span>`).join("")}</div></div>` : `<p class="note">使ってみたい表現は、会話を始める時にAIが用意します。</p>`}
        ${sel && sel !== "seg" ? `<button class="small" id="del" style="background:none;border:none;color:var(--muted);text-align:left;padding:0;text-decoration:underline">このテーマを削除</button>` : ""}
        <button class="btn" id="start" ${cur ? "" : "disabled"}>このテーマで話す</button>
        <p class="small">マイクはChromeかEdgeで使えます</p>
      </aside></div>`;
    document.getElementById("add").onclick = async () => {
      const v = document.getElementById("nt").value.trim(); if (!v) return;
      try { const r = await api("/api/themes", { name: v }); sel = r.new_theme; draw(); } catch (e) { toast(e.message); }
    };
    document.getElementById("nt").onkeydown = (e) => { if (e.key === "Enter") document.getElementById("add").click(); };
    const sb = document.getElementById("seg"); if (sb) sb.onclick = () => { sel = "seg"; draw(); };
    document.getElementById("rand").onclick = () => { const t = themes[Math.floor(Math.random() * themes.length)]; if (t) { sel = t.id; draw(); } };
    document.querySelectorAll("[data-t]").forEach((b) => (b.onclick = () => { sel = b.dataset.t; draw(); }));
    document.querySelectorAll("[data-rmtalk]").forEach((b) => (b.onclick = async () => { try { talks = (await api("/api/talk/delete", { id: b.dataset.rmtalk })).talks; draw(); } catch (e) { toast(e.message); } }));
    document.querySelectorAll("[data-fav]").forEach((b) => (b.onclick = async () => { await api("/api/themes/fav", { id: b.dataset.fav }); draw(); }));
    const del = document.getElementById("del"); if (del) del.onclick = async () => { if (!confirm("このテーマを削除しますか？")) return; await api("/api/themes/delete", { id: sel }); sel = segTheme ? "seg" : (S.progress.themes[0] || {}).id; draw(); };
    document.getElementById("start").onclick = async (e) => {
      busy(e.currentTarget, true, "準備中");
      try {
        const body = sel === "seg" ? { theme: segTheme.name + (segTheme.detail ? `（${segTheme.detail}）` : ""), targets: segTheme.targets.slice(0, 4) } : { theme: cur.name, theme_id: cur.id };
        const t = await api("/api/talk/start", body);
        await refresh(); go(`talk/${t.id}`);
      } catch (err) { toast(err.message, 6000); busy(e.currentTarget, false); }
    };
  };
  if (!talks.length) { try { talks = await api("/api/talks"); } catch (e) { /* noop */ } }
  draw();
};

// ================= 会話 =================
let rec = null, recOn = false;
function stopRec() { if (rec) { try { rec.onend = null; rec.stop(); } catch (e) { /* noop */ } } rec = null; recOn = false; }
function speak(text) {
  if (!window.speechSynthesis || !text) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text); u.lang = "en-US"; u.rate = 0.95;
  const v = speechSynthesis.getVoices().find((x) => /en[-_]US/i.test(x.lang) && /natural|online/i.test(x.name)) || speechSynthesis.getVoices().find((x) => /en[-_]US/i.test(x.lang));
  if (v) u.voice = v;
  speechSynthesis.speak(u);
}
routes.talk = async (tid) => {
  let t = await api(`/api/talk/${tid}`);
  if (!t.id) { go("theme"); return; }
  let showJa = localGet("showJa", true), autoSpeak = localGet("autoSpeak", true), sending = false, live = "";
  const used = () => new Set(t.messages.flatMap((m) => (m.used || []).map((u) => u.toLowerCase())));
  const draw = () => {
    const u = used(); const mine = t.messages.filter((m) => m.role === "me");
    $app.innerHTML = `<div class="small" style="margin-bottom:12px"><a href="#theme">← テーマ選択</a> ・ テーマ：${esc(t.theme)}</div>
    <div class="row">
      <section class="card grow stack">
        <div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end">
          <button class="chip ${showJa ? "on" : ""}" id="ja">日本語訳：${showJa ? "表示" : "非表示"}</button>
          <button class="chip ${autoSpeak ? "on" : ""}" id="sp">${ICON.speaker}読み上げ：${autoSpeak ? "ON" : "OFF"}</button>
        </div>
        <div class="msgs">${t.messages.map((m, i) => `<div class="msg ${m.role === "me" ? "me" : ""}">
          <div class="small">${m.role === "me" ? "あなた" : "AI"}</div>
          <div class="bubble"><div class="en">${esc(m.en)}</div>
            ${m.role === "ai" && showJa && m.ja ? `<div class="ja">${esc(m.ja)}</div>` : ""}
            ${m.correction && m.correction.better ? `<div class="fix"><b>より自然な言い方</b>${esc(m.correction.better)}${m.correction.note_ja ? `<div class="small">${esc(m.correction.note_ja)}</div>` : ""}</div>` : ""}
          </div>
          ${m.role === "ai" ? `<button class="iconbtn" style="width:36px;height:36px" data-say="${i}" aria-label="読み上げ">${ICON.speaker}</button>` : ""}
        </div>`).join("")}
          ${sending ? `<div class="msg"><div class="bubble"><span class="spin"></span></div></div>` : ""}</div>
        <div class="dock" style="border-top:1px solid var(--line2);padding-top:14px;display:flex;flex-direction:column;align-items:center;gap:10px">
          <div class="live" id="live">${esc(live) || '<span class="small">マイクを押して英語で話してください（話した内容がここに文字で出ます）</span>'}</div>
          <button class="mic ${recOn ? "rec" : ""}" id="mic" aria-label="${recOn ? "話し終えた" : "話す"}" ${sending ? "disabled" : ""}>${ICON.mic}</button>
          <span class="small">${recOn ? "録音中 ・ 話し終えたらもう一度押す" : "押して話す"}</span>
          <details style="width:100%"><summary class="small">キーボードで入力する</summary>
            <div class="field" style="margin-top:8px"><input id="typed" type="text" placeholder="Type in English"><button class="btn" id="send" style="border-radius:10px" ${sending ? "disabled" : ""}>送信</button></div></details>
        </div>
      </section>
      <aside class="side stack">
        <section class="card"><h2>使ってみたい表現</h2>
          ${(t.targets || []).map((x) => { const ok = u.has((x.en || "").toLowerCase()); return `<div style="display:flex;justify-content:space-between;gap:8px;padding:8px 0;border-top:1px solid var(--line2)"><div><div style="font-weight:600;color:var(--purpleInk)">${esc(x.en)}</div><div class="small">${esc(x.ja || "")}</div></div><span style="font-size:13px;font-weight:700;color:${ok ? "var(--green)" : "var(--muted)"};white-space:nowrap">${ok ? "✓ 使えた" : "未使用"}</span></div>`; }).join("")}
        </section>
        <section class="card" style="font-size:14px"><h2>この会話</h2>
          <div style="display:flex;justify-content:space-between"><span>話した文</span><b>${mine.length}文</b></div>
          <div style="display:flex;justify-content:space-between"><span>修正提案</span><b>${mine.filter((m) => m.correction && m.correction.better).length}件</b></div>
          <div style="display:flex;justify-content:space-between"><span>目標表現の使用</span><b>${(t.targets || []).filter((x) => u.has((x.en || "").toLowerCase())).length} / ${(t.targets || []).length}</b></div>
        </section>
        <a class="btn" href="#stats">会話を終える</a>
        <p class="small">会話は英文のまま保存され、会話画面の「最近の会話」から見返せます。</p>
      </aside></div>`;
    bind();
    const last = $app.querySelector(".msgs .msg:last-child"); if (last) last.scrollIntoView({ block: "nearest" });
  };
  const send = async (text) => {
    text = (text || "").trim(); if (!text || sending) return;
    sending = true; live = ""; t.messages.push({ role: "me", en: text }); draw();
    try { t = await api("/api/talk/reply", { id: t.id, text }); }
    catch (e) { t.messages.pop(); toast(e.message, 6000); }
    sending = false; draw();
    const lastAi = t.messages[t.messages.length - 1];
    if (autoSpeak && lastAi && lastAi.role === "ai") speak(lastAi.en);
  };
  const bind = () => {
    document.getElementById("ja").onclick = () => { showJa = !showJa; localSet("showJa", showJa); draw(); };
    document.getElementById("sp").onclick = () => { autoSpeak = !autoSpeak; localSet("autoSpeak", autoSpeak); if (!autoSpeak) speechSynthesis.cancel(); draw(); };
    document.querySelectorAll("[data-say]").forEach((b) => (b.onclick = () => speak(t.messages[+b.dataset.say].en)));
    document.getElementById("send").onclick = () => { const v = document.getElementById("typed").value; send(v); };
    document.getElementById("typed").onkeydown = (e) => { if (e.key === "Enter" && !e.isComposing) document.getElementById("send").click(); };
    document.getElementById("mic").onclick = () => {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) { toast("このブラウザは音声認識に対応していません。ChromeかEdgeで開いてください", 6000); return; }
      if (recOn) { const text = live; stopRec(); send(text); return; }
      speechSynthesis.cancel();
      rec = new SR(); rec.lang = "en-US"; rec.interimResults = true; rec.continuous = true;
      let finalText = "";
      rec.onresult = (ev) => {
        let interim = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          if (ev.results[i].isFinal) finalText += ev.results[i][0].transcript + " "; else interim += ev.results[i][0].transcript;
        }
        live = (finalText + interim).trim();
        const el = document.getElementById("live"); if (el) el.textContent = live;
      };
      rec.onerror = (ev) => { if (ev.error === "not-allowed") toast("マイクの使用が許可されていません（アドレスバーの鍵アイコンから許可）", 6000); };
      rec.onend = () => { if (recOn) { try { rec.start(); } catch (e) { /* noop */ } } };
      rec.start(); recOn = true; live = ""; draw();
    };
  };
  draw();
  const first = t.messages[t.messages.length - 1];
  if (autoSpeak && t.messages.length === 1 && first.role === "ai") setTimeout(() => speak(first.en), 300);
};
