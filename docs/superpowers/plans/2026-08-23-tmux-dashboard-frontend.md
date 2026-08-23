# tmuxエージェント監視フロントエンド Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tmux-dashboard`バックエンド（`http://localhost:3000`）と通信し、複数のtmuxエージェントの状態監視・指示送信を行うWebダッシュボードを実装する。

**Architecture:** バニラJS/HTML/CSSの単一ファイル`tmux-dashboard/public/index.html`。追加npm依存なしの最小静的サーバー`tmux-dashboard/serve.js`で配信（既定ポート8080）。バックエンドとは別ポートで動作し、既存のCORS設定でfetch/WebSocket通信する。

**Tech Stack:** バニラJS（フレームワークなし）、Node標準`http`/`fs`モジュールのみ（追加npm依存なし）。

**Spec:** [docs/superpowers/specs/2026-08-23-tmux-dashboard-frontend-design.md](../specs/2026-08-23-tmux-dashboard-frontend-design.md)

## Global Constraints

- 追加npm依存は禁止（`serve.js`はNode標準モジュールのみ）。
- 外部CDN依存禁止（フォント・JSライブラリ等は使わない）。
- 配色は`cost_dashboard.html`のダークテーマを踏襲: 背景`#0f0f1a`、カード`#1e1e2e`、ボーダー`#2d2d44`、文字`#e2e8f0`、アクセント`#a78bfa`。
- **本プランはTDD（自動テスト）を採用しない** — spec自己レビュー時点でユーザー承認済みの設計判断（単一HTMLファイル内のロジックを`window`にぶら下げてまで自動テスト化するより、Browser toolによる実機確認を優先する）。各タスクは「実装 → Browser toolまたはcurlで動作確認 → コミット」のサイクルで進める。
- `API_BASE`定数（既定`http://localhost:3000`）を`index.html`先頭に置き、以後すべてのfetch/WebSocket呼び出しはこれを参照する。
- 1コミットの変更は200行以内。タスク内でも大きくなる場合はステップごとに分割コミットする。

---

### Task 1: serve.js — 静的配信サーバー

**Files:**
- Create: `tmux-dashboard/serve.js`
- Modify: `tmux-dashboard/package.json`（`"scripts"`に`"serve"`を追加）

**Interfaces:**
- Consumes: なし
- Produces: `tmux-dashboard/public/`配下の静的ファイルを配信するHTTPサーバー。ポートは`process.env.SERVE_PORT`または既定`8080`。

- [ ] **Step 1: serve.js を実装**

```javascript
// tmux-dashboard/serve.js
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const PORT = process.env.SERVE_PORT || 8080;
const PUBLIC_DIR = path.join(__dirname, 'public');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
};

const server = http.createServer((req, res) => {
  const urlPath = req.url === '/' ? '/index.html' : req.url;
  const filePath = path.join(PUBLIC_DIR, decodeURIComponent(urlPath.split('?')[0]));

  if (!filePath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not Found');
      return;
    }
    const ext = path.extname(filePath);
    res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
    res.end(content);
  });
});

server.listen(PORT, () => {
  console.log(`tmux-dashboard frontend listening on port ${PORT}`);
});
```

- [ ] **Step 2: public/ ディレクトリと最小限のindex.htmlプレースホルダーを作成（Task 2で本実装するまでの疎通確認用）**

```html
<!-- tmux-dashboard/public/index.html -->
<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"><title>tmux dashboard</title></head>
<body>placeholder</body>
</html>
```

- [ ] **Step 3: package.json に serve スクリプトを追加**

`tmux-dashboard/package.json`の`"scripts"`ブロックを以下に更新:

```json
  "scripts": {
    "start": "node server.js",
    "test": "node --test",
    "serve": "node serve.js"
  },
```

- [ ] **Step 4: サーバーを起動して疎通確認**

Run:
```bash
cd tmux-dashboard && SERVE_PORT=8080 node serve.js &
sleep 1
curl -s -w "\nHTTP_STATUS:%{http_code}\n" http://localhost:8080/
curl -s -w "\nHTTP_STATUS:%{http_code}\n" http://localhost:8080/nonexistent.html
```
Expected: 1つ目は200で`placeholder`を含むHTML、2つ目は404。確認後 `kill %1` 等でプロセスを停止する。

- [ ] **Step 5: Commit**

```bash
git add tmux-dashboard/serve.js tmux-dashboard/package.json tmux-dashboard/public/index.html
git commit -m "feat(tmux-dashboard): フロントエンド用の静的配信サーバーを追加"
```

---

### Task 2: index.html — 静的構造とスタイル（ヘッダー・一斉送信バー・カードグリッド枠・モーダル枠）

**Files:**
- Modify: `tmux-dashboard/public/index.html`（Task 1のプレースホルダーを置き換え）

**Interfaces:**
- Consumes: なし（この時点ではJSロジックなし、静的マークアップとCSSのみ）
- Produces: 以降のタスクがJSから参照するDOM要素のid一覧:
  - `#connection-status`（ヘッダーの接続状態インジケーター）
  - `#broadcast-input`, `#broadcast-button`（一斉送信バー）
  - `#agent-grid`（カードを挿入するコンテナ）
  - `#output-modal`, `#output-modal-title`, `#output-modal-body`, `#output-modal-close`（`<dialog>`モーダル）
  - `#toast-container`（トースト表示用コンテナ）
  - `<template id="agent-card-template">`（カードのDOMテンプレート。Task 3でJSから`content.cloneNode(true)`して使う）

- [ ] **Step 1: index.html を作成（構造 + CSS、JSはまだ書かない）**

```html
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>tmux エージェント監視ダッシュボード</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0f0f1a;
    color: #e2e8f0;
    min-height: 100vh;
    padding: 24px;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20px;
  }
  h1 {
    font-size: 1.5rem;
    font-weight: 700;
    color: #a78bfa;
    letter-spacing: -0.02em;
  }
  #connection-status {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.85rem;
    color: #94a3b8;
  }
  #connection-status .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #f87171;
  }
  #connection-status.connected .dot { background: #4ade80; }
  #connection-status.connected .label::after { content: '接続中'; }
  #connection-status:not(.connected) .label::after { content: '切断・再接続中'; }

  .broadcast-bar {
    display: flex;
    gap: 8px;
    margin-bottom: 24px;
    background: #1e1e2e;
    border: 1px solid #2d2d44;
    border-radius: 12px;
    padding: 12px 16px;
  }
  .broadcast-bar input {
    flex: 1;
    background: #0f0f1a;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    color: #e2e8f0;
    padding: 8px 12px;
    font-size: 0.9rem;
  }
  button {
    background: #a78bfa;
    color: #0f0f1a;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 0.85rem;
    cursor: pointer;
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }

  #agent-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
  }
  .agent-card {
    background: #1e1e2e;
    border: 1px solid #2d2d44;
    border-radius: 12px;
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .agent-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .agent-name { font-weight: 600; font-size: 1rem; }
  .status-badge {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 3px 10px;
    border-radius: 999px;
    color: #0f0f1a;
  }
  .status-badge.working { background: #4ade80; }
  .status-badge.waiting_input { background: #facc15; }
  .status-badge.idle { background: #94a3b8; }
  .status-badge.stale { background: #fb923c; }
  .status-badge.not_running { background: #475569; color: #cbd5e1; }
  .status-badge.unresponsive { background: #f87171; }

  .agent-output-preview {
    background: #0f0f1a;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    padding: 8px 10px;
    font-family: 'Consolas', monospace;
    font-size: 0.78rem;
    color: #94a3b8;
    white-space: pre-wrap;
    max-height: 90px;
    overflow: hidden;
    cursor: pointer;
  }
  .agent-elapsed { font-size: 0.75rem; color: #64748b; }

  .agent-send-row { display: flex; gap: 8px; }
  .agent-send-row input {
    flex: 1;
    background: #0f0f1a;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    color: #e2e8f0;
    padding: 6px 10px;
    font-size: 0.82rem;
  }
  .agent-send-feedback { font-size: 0.72rem; min-height: 1em; }
  .agent-send-feedback.ok { color: #4ade80; }
  .agent-send-feedback.error { color: #f87171; }

  dialog#output-modal {
    background: #1e1e2e;
    color: #e2e8f0;
    border: 1px solid #2d2d44;
    border-radius: 12px;
    padding: 20px;
    width: min(700px, 90vw);
    max-height: 80vh;
  }
  dialog#output-modal::backdrop { background: rgba(0,0,0,0.6); }
  #output-modal-body {
    font-family: 'Consolas', monospace;
    font-size: 0.8rem;
    white-space: pre-wrap;
    overflow-y: auto;
    max-height: 55vh;
    margin: 12px 0;
  }

  #toast-container {
    position: fixed;
    bottom: 20px;
    right: 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .toast {
    background: #1e1e2e;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 0.82rem;
  }
  .toast.error { border-color: #f87171; color: #fca5a5; }

  #load-error {
    background: #1e1e2e;
    border: 1px solid #f87171;
    color: #fca5a5;
    border-radius: 12px;
    padding: 16px 20px;
    display: none;
  }
</style>
</head>
<body>
  <header>
    <h1>tmux エージェント監視ダッシュボード</h1>
    <div id="connection-status"><span class="dot"></span><span class="label"></span></div>
  </header>

  <div id="load-error"></div>

  <div class="broadcast-bar">
    <input type="text" id="broadcast-input" placeholder="全エージェントへの指示を入力...">
    <button id="broadcast-button">全員に送信</button>
  </div>

  <div id="agent-grid"></div>

  <template id="agent-card-template">
    <div class="agent-card">
      <div class="agent-card-header">
        <span class="agent-name"></span>
        <span class="status-badge"></span>
      </div>
      <pre class="agent-output-preview"></pre>
      <div class="agent-elapsed"></div>
      <div class="agent-send-row">
        <input type="text" class="agent-send-input" placeholder="指示を入力...">
        <button class="agent-send-button">送信</button>
      </div>
      <div class="agent-send-feedback"></div>
    </div>
  </template>

  <dialog id="output-modal">
    <strong id="output-modal-title"></strong>
    <div id="output-modal-body"></div>
    <button id="output-modal-close">閉じる</button>
  </dialog>

  <div id="toast-container"></div>
</body>
</html>
```

- [ ] **Step 2: Browser toolで静的表示を確認**

`mcp__Claude_Browser__preview_start`で`tmux-dashboard/public/index.html`をfile://で、またはTask 1の`serve.js`を起動して`http://localhost:8080`を開く。ヘッダー・一斉送信バー・空のカードグリッド枠・トースト用領域が崩れずダークテーマで表示されることを確認する（この時点ではカードは0件、モーダルは非表示のままでよい）。

- [ ] **Step 3: Commit**

```bash
git add tmux-dashboard/public/index.html
git commit -m "feat(tmux-dashboard): フロントエンドの静的構造とスタイルを追加"
```

---

### Task 3: JS — 初期表示・カード描画・経過時間表示

**Files:**
- Modify: `tmux-dashboard/public/index.html`（`<script>`ブロックを追加）

**Interfaces:**
- Consumes: Task 2のDOM要素id群、バックエンドの`GET /api/agents`レスポンス形式`{agents: [{id,name,session,status,lastOutputPreview,lastChangedAt,elapsedSec}]}`
- Produces:
  - `const API_BASE = 'http://localhost:3000';`（以降の全タスクが参照する定数）
  - `const agentsById = new Map();`（id→最新agentデータのキャッシュ。Task 4以降のWS更新もここを更新する）
  - `function renderAgentCard(agent)` → 新規`.agent-card`のDOM要素を生成して返す（`agentsById`には登録しない、呼び出し側が登録する）
  - `function updateAgentCard(cardEl, agent)` → 既存カードDOM要素の中身を最新agentデータで更新する
  - `function formatElapsed(sec)` → `string`（例: `"3秒前"`, `"2分前"`, `"1時間前"`）
  - `function loadInitialAgents()` → `GET /api/agents`をfetchし、`agentsById`を埋めて`#agent-grid`にカードを描画する。失敗時は`#load-error`を表示する。
  - 1秒間隔の`setInterval`で全カードの経過時間表示のみを更新する（`agentsById`の`lastChangedAt`から再計算）

- [ ] **Step 1: `</body>`直前に`<script>`ブロックを追加**

```html
<script>
const API_BASE = 'http://localhost:3000';
const agentsById = new Map();
const cardElementsById = new Map();

function formatElapsed(sec) {
  if (sec < 60) return `${sec}秒前`;
  if (sec < 3600) return `${Math.floor(sec / 60)}分前`;
  return `${Math.floor(sec / 3600)}時間前`;
}

function computeElapsedSec(agent) {
  const changedAt = new Date(agent.lastChangedAt).getTime();
  return Math.max(0, Math.floor((Date.now() - changedAt) / 1000));
}

function renderAgentCard(agent) {
  const template = document.getElementById('agent-card-template');
  const card = template.content.cloneNode(true).querySelector('.agent-card');
  updateAgentCard(card, agent);
  card.querySelector('.agent-output-preview').addEventListener('click', () => openOutputModal(agent.id));
  return card;
}

function updateAgentCard(cardEl, agent) {
  cardEl.dataset.agentId = agent.id;
  cardEl.querySelector('.agent-name').textContent = agent.name;
  const badge = cardEl.querySelector('.status-badge');
  badge.textContent = agent.status;
  badge.className = `status-badge ${agent.status}`;
  cardEl.querySelector('.agent-output-preview').textContent = agent.lastOutputPreview || '(出力なし)';
  cardEl.querySelector('.agent-elapsed').textContent = formatElapsed(computeElapsedSec(agent));
}

function upsertCard(agent) {
  agentsById.set(agent.id, agent);
  let card = cardElementsById.get(agent.id);
  if (!card) {
    card = renderAgentCard(agent);
    cardElementsById.set(agent.id, card);
    document.getElementById('agent-grid').appendChild(card);
  } else {
    updateAgentCard(card, agent);
  }
}

async function loadInitialAgents() {
  try {
    const res = await fetch(`${API_BASE}/api/agents`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    body.agents.forEach(upsertCard);
    document.getElementById('load-error').style.display = 'none';
  } catch (err) {
    const el = document.getElementById('load-error');
    el.textContent = `バックエンドに接続できません（${API_BASE}）: ${err.message}`;
    el.style.display = 'block';
  }
}

setInterval(() => {
  cardElementsById.forEach((card, id) => {
    const agent = agentsById.get(id);
    if (!agent) return;
    card.querySelector('.agent-elapsed').textContent = formatElapsed(computeElapsedSec(agent));
  });
}, 1000);

loadInitialAgents();
</script>
```

（`openOutputModal`はTask 5で定義するため、この時点ではまだ存在しない未定義関数呼び出しになるが、クリックしなければ実行されないのでTask 3単体の動作確認には影響しない）

- [ ] **Step 2: バックエンドとフロントエンドを両方起動しBrowser toolで確認**

```bash
cd tmux-dashboard && cp -n agents.example.json agents.json; node server.js &
cd tmux-dashboard && node serve.js &
```
`http://localhost:8080`をBrowser toolで開き、`agents.example.json`の2エージェント（`not_running`状態のはず）がカードとして表示され、経過時間が1秒ごとにカウントアップすることを確認する。確認後両プロセスを停止する。

- [ ] **Step 3: Commit**

```bash
git add tmux-dashboard/public/index.html
git commit -m "feat(tmux-dashboard): フロントエンドの初期表示とカード描画を追加"
```

---

### Task 4: JS — WebSocket接続・自動更新・切断検知

**Files:**
- Modify: `tmux-dashboard/public/index.html`

**Interfaces:**
- Consumes: Task 3の`upsertCard`, `agentsById`, `API_BASE`。バックエンドのWSメッセージ形式`{type:"snapshot"|"update", agents:[...]}`
- Produces:
  - `function connectWebSocket()` → WebSocket接続を開始し、`onopen`/`onmessage`/`onclose`/`onerror`を設定する。切断時は2秒後に自身を再帰呼び出しして再接続する。
  - `function setConnectionStatus(connected: boolean)` → `#connection-status`の`connected`クラスを切り替える

- [ ] **Step 1: `loadInitialAgents();`の直後に追記**

```html
<script>
function setConnectionStatus(connected) {
  const el = document.getElementById('connection-status');
  el.classList.toggle('connected', connected);
}

function connectWebSocket() {
  const wsUrl = API_BASE.replace(/^http/, 'ws') + '/ws';
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => setConnectionStatus(true);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'snapshot' || msg.type === 'update') {
      msg.agents.forEach(upsertCard);
    }
  };

  ws.onclose = () => {
    setConnectionStatus(false);
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = () => ws.close();
}

connectWebSocket();
</script>
```

- [ ] **Step 2: Browser toolで確認**

バックエンド・フロントエンドを起動しページを開く。接続状態インジケーターが緑「接続中」になることを確認する。次にバックエンドプロセスを停止し、インジケーターが赤「切断・再接続中」に変わることを確認する。バックエンドを再起動し、数秒以内にインジケーターが緑に戻ることを確認する。

- [ ] **Step 3: Commit**

```bash
git add tmux-dashboard/public/index.html
git commit -m "feat(tmux-dashboard): WebSocketリアルタイム更新と切断検知を追加"
```

---

### Task 5: JS — 出力全文モーダル

**Files:**
- Modify: `tmux-dashboard/public/index.html`

**Interfaces:**
- Consumes: Task 3の`API_BASE`。バックエンドの`GET /api/agents/:id/output`レスポンス`{id, session, output}`
- Produces: `function openOutputModal(agentId)`（Task 3の`renderAgentCard`内クリックハンドラから既に参照されている関数を実装する）

- [ ] **Step 1: `connectWebSocket();`の直後に追記**

```html
<script>
async function openOutputModal(agentId) {
  const modal = document.getElementById('output-modal');
  const agent = agentsById.get(agentId);
  document.getElementById('output-modal-title').textContent = agent ? agent.name : agentId;
  document.getElementById('output-modal-body').textContent = '読み込み中...';
  modal.showModal();

  try {
    const res = await fetch(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}/output`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    document.getElementById('output-modal-body').textContent = body.output || '(出力なし)';
  } catch (err) {
    document.getElementById('output-modal-body').textContent = `取得に失敗しました: ${err.message}`;
  }
}

document.getElementById('output-modal-close').addEventListener('click', () => {
  document.getElementById('output-modal').close();
});
</script>
```

- [ ] **Step 2: Browser toolで確認**

カードの出力プレビュー部分をクリックし、モーダルが開いて出力全文（`agents.example.json`のセッションは`not_running`なので出力は空「(出力なし)」表示になるはず）が表示されることを確認する。「閉じる」ボタンでモーダルが閉じることを確認する。

- [ ] **Step 3: Commit**

```bash
git add tmux-dashboard/public/index.html
git commit -m "feat(tmux-dashboard): 出力全文モーダルを追加"
```

---

### Task 6: JS — 個別送信・一斉送信

**Files:**
- Modify: `tmux-dashboard/public/index.html`

**Interfaces:**
- Consumes: Task 3の`API_BASE`, `renderAgentCard`（送信ボタンのイベントリスナーをここに追加する）
- Produces:
  - `function showToast(message, isError)` → `#toast-container`に3秒で消えるトーストを追加する
  - `renderAgentCard`内: 送信ボタンクリック/Enterキーで`POST /api/agents/:id/send`を呼ぶハンドラ
  - `#broadcast-button`クリックで`POST /api/agents/broadcast`を呼ぶハンドラ

- [ ] **Step 1: `showToast`とbroadcastハンドラを追加**

```html
<script>
function showToast(message, isError) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast${isError ? ' error' : ''}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

document.getElementById('broadcast-button').addEventListener('click', async () => {
  const input = document.getElementById('broadcast-input');
  const text = input.value.trim();
  if (!text) return;
  const button = document.getElementById('broadcast-button');
  button.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/agents/broadcast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const body = await res.json();
    const okCount = body.results.filter((r) => r.ok).length;
    const failCount = body.results.length - okCount;
    showToast(`一斉送信: 成功${okCount}件 / 失敗${failCount}件`, failCount > 0);
    input.value = '';
  } catch (err) {
    showToast(`一斉送信に失敗しました: ${err.message}`, true);
  } finally {
    button.disabled = false;
  }
});
</script>
```

- [ ] **Step 2: `renderAgentCard`関数を更新して個別送信ハンドラを追加**

`renderAgentCard`関数内の`return card;`の直前に追記:

```javascript
  const sendInput = card.querySelector('.agent-send-input');
  const sendButton = card.querySelector('.agent-send-button');
  const feedback = card.querySelector('.agent-send-feedback');

  async function sendToAgent() {
    const text = sendInput.value.trim();
    if (!text) return;
    sendButton.disabled = true;
    feedback.textContent = '';
    feedback.className = 'agent-send-feedback';
    try {
      const res = await fetch(`${API_BASE}/api/agents/${encodeURIComponent(agent.id)}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
      feedback.textContent = '送信しました';
      feedback.className = 'agent-send-feedback ok';
      sendInput.value = '';
    } catch (err) {
      feedback.textContent = err.message;
      feedback.className = 'agent-send-feedback error';
    } finally {
      sendButton.disabled = false;
      setTimeout(() => { feedback.textContent = ''; feedback.className = 'agent-send-feedback'; }, 3000);
    }
  }

  sendButton.addEventListener('click', sendToAgent);
  sendInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendToAgent();
  });
```

- [ ] **Step 3: Browser toolで確認**

1. 個別カードの入力欄にテキストを入れて送信ボタンをクリック。`agents.example.json`のセッションは`not_running`なので409エラーが返り、カード上に赤字でエラーメッセージが3秒表示されることを確認する。
2. 一斉送信バーも同様に、失敗件数を含むトーストが表示されることを確認する。
3. （任意）WSL側に実際に`tmux new-session -d -s cc-agent1`等でテスト用セッションを作成できる場合は、送信が成功しトーストが緑系表示になることも確認する。作成できない環境では409系の確認のみで良い。

- [ ] **Step 4: Commit**

```bash
git add tmux-dashboard/public/index.html
git commit -m "feat(tmux-dashboard): 個別送信・一斉送信を追加"
```

---

### Task 7: 統合確認とREADME更新

**Files:**
- Modify: `tmux-dashboard/README.md`（フロントエンドのセットアップ・起動方法を追記）

**Interfaces:**
- Consumes: Task 1〜6の全成果物

- [ ] **Step 1: README.mdに「フロントエンド」セクションを追記**

`tmux-dashboard/README.md`の「## テスト」セクションの直前に挿入:

```markdown
## フロントエンド

`public/index.html` にバニラJSのダッシュボードがあります。追加のnpm依存はありません。

\`\`\`bash
npm run serve
\`\`\`

既定で `http://localhost:8080` で配信されます。`public/index.html` 内の `API_BASE` 定数（既定 `http://localhost:3000`）を編集すればバックエンドの接続先を変更できます。
```

- [ ] **Step 2: バックエンド・フロントエンドを同時起動し、Browser toolで一通り操作して最終確認**

```bash
cd tmux-dashboard && cp -n agents.example.json agents.json
node server.js &
node serve.js &
```
Browser toolで`http://localhost:8080`を開き、以下を一通り確認する:
- カード一覧・状態バッジ・経過時間の表示
- 出力プレビュークリック→モーダル表示→閉じる
- 個別送信・一斉送信のエラー表示
- WebSocket接続状態インジケーターの表示

確認後、両プロセスを停止する。

- [ ] **Step 3: Commit**

```bash
git add tmux-dashboard/README.md
git commit -m "docs(tmux-dashboard): READMEにフロントエンドのセットアップ手順を追加"
```

- [ ] **Step 4: fresh context検証**

会話の文脈を持たないエージェントに、`tmux-dashboard/public/index.html`と`tmux-dashboard/serve.js`を読ませ、元のユーザー要求（カード一覧・状態バッジ色分け・出力プレビューとモーダル・経過時間表示・個別/一斉送信・WebSocket自動更新と切断表示・ダッシュボードらしい配色）を満たしているか検証させる。

- [ ] **Step 5: 最終bash判定**

```bash
#!/bin/bash
set -e
cd tmux-dashboard
git diff <base-branch> --stat --exit-code --quiet -- . && echo "NO CHANGES" && exit 1
node -e "require('./serve.js')" &
SERVER_PID=$!
sleep 1
curl -sf http://localhost:8080/ > /dev/null
kill $SERVER_PID
echo "DONE"
```
