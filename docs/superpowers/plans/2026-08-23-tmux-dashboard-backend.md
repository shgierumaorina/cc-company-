# tmux エージェント監視バックエンドサーバー Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** tmuxで並行実行している複数のClaude Codeセッションを監視・操作するAPI/WebSocketサーバー（`cc-company/tmux-dashboard/`）を実装する。

**Architecture:** Node.js + Express + ws の単一プロセス。単一のpollerループがWSL経由でtmuxコマンドを定期実行し、判定結果をメモリ上のstateストアに保持する。REST/WebSocketはこのキャッシュを読むだけで、リクエストの都度tmuxは叩かない。状態判定ロジックとtmuxコマンド引数構築は純粋関数として分離し、ユニットテスト可能にする。

**Tech Stack:** Node.js (>=18, 組み込み`fetch`と`node:test`を使用), Express, ws, cors。依存追加はこの3パッケージのみ。

**Spec:** [docs/superpowers/specs/2026-08-23-tmux-dashboard-backend-design.md](../specs/2026-08-23-tmux-dashboard-backend-design.md)

## Global Constraints

- 依存パッケージは `express`, `ws`, `cors` のみ。他の追加禁止。
- tmux呼び出しは `child_process.execFile('wsl', [...])` で行い、`exec`（シェル文字列結合）は使わない。
- 1コミットの変更は200行以内。タスク内でも大きくなる場合はステップごとに分割コミットする。
- 認証なし・ローカル利用専用。CORSは全オリジン許可。
- ポート既定3000、`config.json`で上書き可能。
- テストは `node:test` + `node:assert`（追加依存なし）。HTTPテストはNode組み込み`fetch`を使う。
- `agents.json`は環境依存（実際のtmuxセッション名）のため`.gitignore`対象。リポジトリには`agents.example.json`を含める。

---

### Task 1: プロジェクトscaffold

**Files:**
- Create: `tmux-dashboard/package.json`
- Create: `tmux-dashboard/.gitignore`
- Create: `tmux-dashboard/config.json`
- Create: `tmux-dashboard/agents.example.json`

**Interfaces:**
- Produces: `config.json`のキー `PORT`, `POLL_INTERVAL_MS`, `IDLE_THRESHOLD_SEC`, `STALE_THRESHOLD_SEC`, `OUTPUT_LINES`（以降の全タスクがこれを読む）
- Produces: `agents.example.json`の形式 `[{"id": string, "name": string, "session": string}]`（以降の全タスクがこの形式を前提とする）

- [ ] **Step 1: package.json を作成**

```json
{
  "name": "tmux-dashboard",
  "version": "1.0.0",
  "private": true,
  "description": "tmuxで並行実行しているエージェントセッションの監視・操作API/WebSocketサーバー",
  "main": "server.js",
  "type": "commonjs",
  "engines": { "node": ">=18" },
  "scripts": {
    "start": "node server.js",
    "test": "node --test"
  },
  "dependencies": {
    "cors": "^2.8.5",
    "express": "^4.19.2",
    "ws": "^8.18.0"
  }
}
```

- [ ] **Step 2: .gitignore を作成**

```
node_modules/
agents.json
```

- [ ] **Step 3: config.json を作成**

```json
{
  "PORT": 3000,
  "POLL_INTERVAL_MS": 2500,
  "IDLE_THRESHOLD_SEC": 60,
  "STALE_THRESHOLD_SEC": 300,
  "OUTPUT_LINES": 200
}
```

- [ ] **Step 4: agents.example.json を作成**

```json
[
  { "id": "agent1", "name": "リサーチ担当", "session": "cc-agent1" },
  { "id": "agent2", "name": "コンテンツ担当", "session": "cc-agent2" }
]
```

- [ ] **Step 5: 依存インストール**

Run: `cd tmux-dashboard && npm install`
Expected: `node_modules/`が作成され、`package-lock.json`が生成される。

- [ ] **Step 6: Commit**

```bash
git add tmux-dashboard/package.json tmux-dashboard/package-lock.json tmux-dashboard/.gitignore tmux-dashboard/config.json tmux-dashboard/agents.example.json
git commit -m "chore(tmux-dashboard): プロジェクトscaffoldを作成"
```

---

### Task 2: lib/tmux.js — tmuxコマンドラッパー

**Files:**
- Create: `tmux-dashboard/lib/tmux.js`
- Test: `tmux-dashboard/lib/tmux.test.js`

**Interfaces:**
- Consumes: なし
- Produces:
  - `buildListSessionsArgs()` → `string[]`（`wsl`に渡す引数配列）
  - `buildCapturePaneArgs(session: string, lines: number)` → `string[]`
  - `buildSendKeysArgs(session: string, text: string)` → `string[]`
  - `async listSessions()` → `Promise<string[]>`（tmuxセッション名の配列。tmux未起動時やセッション0件時は`[]`）
  - `async capturePane(session: string, lines: number)` → `Promise<string>`（pane出力全文、失敗時はthrow）
  - `async sendKeys(session: string, text: string)` → `Promise<void>`（失敗時はthrow）

- [ ] **Step 1: 引数構築の失敗するテストを書く**

```javascript
// tmux-dashboard/lib/tmux.test.js
const test = require('node:test');
const assert = require('node:assert');
const {
  buildListSessionsArgs,
  buildCapturePaneArgs,
  buildSendKeysArgs,
} = require('./tmux');

test('buildListSessionsArgs returns tmux list-sessions args', () => {
  assert.deepStrictEqual(buildListSessionsArgs(), [
    '-e', 'tmux', 'list-sessions', '-F', '#S',
  ]);
});

test('buildCapturePaneArgs returns tmux capture-pane args with line limit', () => {
  assert.deepStrictEqual(buildCapturePaneArgs('cc-agent1', 200), [
    '-e', 'tmux', 'capture-pane', '-t', 'cc-agent1', '-p', '-S', '-200',
  ]);
});

test('buildSendKeysArgs keeps text as a single array element (no shell join)', () => {
  const args = buildSendKeysArgs('cc-agent1', 'echo "hello"; rm -rf /');
  assert.deepStrictEqual(args, [
    '-e', 'tmux', 'send-keys', '-t', 'cc-agent1',
    'echo "hello"; rm -rf /', 'Enter',
  ]);
});
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd tmux-dashboard && node --test lib/tmux.test.js`
Expected: FAIL（`./tmux`モジュールが存在しない）

- [ ] **Step 3: lib/tmux.js を実装**

```javascript
// tmux-dashboard/lib/tmux.js
const { execFile } = require('node:child_process');

function buildListSessionsArgs() {
  return ['-e', 'tmux', 'list-sessions', '-F', '#S'];
}

function buildCapturePaneArgs(session, lines) {
  return ['-e', 'tmux', 'capture-pane', '-t', session, '-p', '-S', `-${lines}`];
}

function buildSendKeysArgs(session, text) {
  return ['-e', 'tmux', 'send-keys', '-t', session, text, 'Enter'];
}

function runWsl(args) {
  return new Promise((resolve, reject) => {
    execFile('wsl', args, { maxBuffer: 1024 * 1024 * 10 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(stderr || error.message));
        return;
      }
      resolve(stdout);
    });
  });
}

async function listSessions() {
  try {
    const stdout = await runWsl(buildListSessionsArgs());
    return stdout.split('\n').map((s) => s.trim()).filter(Boolean);
  } catch (err) {
    // tmuxがセッション0件のとき "no server running on ..." 等をstderrに出しexit非0になる。
    // これは「セッション無し」として扱い、それ以外のエラーと区別しない（呼び出し側でlist-sessions失敗=0件扱い）。
    return [];
  }
}

async function capturePane(session, lines) {
  return runWsl(buildCapturePaneArgs(session, lines));
}

async function sendKeys(session, text) {
  await runWsl(buildSendKeysArgs(session, text));
}

module.exports = {
  buildListSessionsArgs,
  buildCapturePaneArgs,
  buildSendKeysArgs,
  listSessions,
  capturePane,
  sendKeys,
};
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test lib/tmux.test.js`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
git add tmux-dashboard/lib/tmux.js tmux-dashboard/lib/tmux.test.js
git commit -m "feat(tmux-dashboard): tmuxコマンドラッパーを追加"
```

---

### Task 3: lib/state.js — メモリ状態ストア

**Files:**
- Create: `tmux-dashboard/lib/state.js`
- Test: `tmux-dashboard/lib/state.test.js`

**Interfaces:**
- Consumes: なし
- Produces:
  - `createState()` → `State`インスタンス
  - `State.setAgent(id: string, data: object)` → `void`（`data`は`{name, session, status, rawOutput, lastChangedAt}`を含む）
  - `State.getAgent(id: string)` → `object | undefined`
  - `State.getAllIds()` → `string[]`
  - `formatAgentSummary(id: string, data: object, now: Date)` → `{id, name, session, status, lastOutputPreview, lastChangedAt, elapsedSec}`（`lastOutputPreview`は`rawOutput`の末尾5行を`\n`結合したもの）

- [ ] **Step 1: 失敗するテストを書く**

```javascript
// tmux-dashboard/lib/state.test.js
const test = require('node:test');
const assert = require('node:assert');
const { createState, formatAgentSummary } = require('./state');

test('setAgent then getAgent returns stored data', () => {
  const state = createState();
  state.setAgent('agent1', { name: 'A', session: 's1', status: 'working', rawOutput: 'line1\nline2', lastChangedAt: new Date('2026-08-23T00:00:00Z') });
  const got = state.getAgent('agent1');
  assert.strictEqual(got.name, 'A');
  assert.strictEqual(got.status, 'working');
});

test('getAgent returns undefined for unknown id', () => {
  const state = createState();
  assert.strictEqual(state.getAgent('nope'), undefined);
});

test('getAllIds returns all registered ids', () => {
  const state = createState();
  state.setAgent('a', { name: 'A', session: 's', status: 'idle', rawOutput: '', lastChangedAt: new Date() });
  state.setAgent('b', { name: 'B', session: 's2', status: 'idle', rawOutput: '', lastChangedAt: new Date() });
  assert.deepStrictEqual(state.getAllIds().sort(), ['a', 'b']);
});

test('formatAgentSummary builds preview from last 5 lines and computes elapsedSec', () => {
  const lines = Array.from({ length: 10 }, (_, i) => `line${i}`);
  const lastChangedAt = new Date('2026-08-23T00:00:00.000Z');
  const now = new Date('2026-08-23T00:00:12.000Z');
  const summary = formatAgentSummary('agent1', {
    name: 'A', session: 's1', status: 'idle', rawOutput: lines.join('\n'), lastChangedAt,
  }, now);
  assert.strictEqual(summary.id, 'agent1');
  assert.strictEqual(summary.lastOutputPreview, lines.slice(-5).join('\n'));
  assert.strictEqual(summary.elapsedSec, 12);
  assert.strictEqual(summary.lastChangedAt, lastChangedAt.toISOString());
});
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd tmux-dashboard && node --test lib/state.test.js`
Expected: FAIL（`./state`モジュールが存在しない）

- [ ] **Step 3: lib/state.js を実装**

```javascript
// tmux-dashboard/lib/state.js
function createState() {
  const agents = new Map();
  return {
    setAgent(id, data) {
      agents.set(id, data);
    },
    getAgent(id) {
      return agents.get(id);
    },
    getAllIds() {
      return Array.from(agents.keys());
    },
  };
}

function formatAgentSummary(id, data, now) {
  const lines = data.rawOutput ? data.rawOutput.split('\n') : [];
  const preview = lines.slice(-5).join('\n');
  const elapsedSec = Math.floor((now.getTime() - data.lastChangedAt.getTime()) / 1000);
  return {
    id,
    name: data.name,
    session: data.session,
    status: data.status,
    lastOutputPreview: preview,
    lastChangedAt: data.lastChangedAt.toISOString(),
    elapsedSec,
  };
}

module.exports = { createState, formatAgentSummary };
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test lib/state.test.js`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
git add tmux-dashboard/lib/state.js tmux-dashboard/lib/state.test.js
git commit -m "feat(tmux-dashboard): メモリ状態ストアを追加"
```

---

### Task 4: lib/poller.js — 状態判定ロジックとポーリングループ

**Files:**
- Create: `tmux-dashboard/lib/poller.js`
- Test: `tmux-dashboard/lib/poller.test.js`

**Interfaces:**
- Consumes: `lib/tmux.js`の`listSessions/capturePane`と同じシグネチャ（テストではモックを注入）、`lib/state.js`の`createState()`が返すインスタンスと同じインターフェース
- Produces:
  - `matchesWaitingInputPattern(output: string)` → `boolean`
  - `determineStatus({ sessionExists, captureError, outputChanged, output, secondsSinceChange, idleThresholdSec, staleThresholdSec })` → `'not_running' | 'unresponsive' | 'working' | 'waiting_input' | 'idle' | 'stale'`
  - `async pollOnce({ agentsConfig, tmux, state, outputLines, idleThresholdSec, staleThresholdSec, now })` → `Promise<string[]>`（今回のポーリングで状態が変化したagent idの配列。`agentsConfig`は`[{id, name, session}]`、`tmux`/`state`は上記インターフェースを満たすオブジェクト、`now`は`Date`）
  - `startPolling({ agentsConfig, tmux, state, config, onChange })` → `stop(): void`（`config`は`config.json`の内容、`onChange`は`(changedIds: string[]) => void`。呼び出し直後に`pollOnce`を1回即時実行し、以降`config.POLL_INTERVAL_MS`ごとに実行する。これは起動直後に`GET /api/agents`が空配列を返すのを避けるため — `setInterval`は最初の実行が1周期後になるため、即時実行がないとサーバー起動から最大`POLL_INTERVAL_MS`の間stateが空になる）

- [ ] **Step 1: 失敗するテストを書く（determineStatus / matchesWaitingInputPattern）**

```javascript
// tmux-dashboard/lib/poller.test.js
const test = require('node:test');
const assert = require('node:assert');
const { determineStatus, matchesWaitingInputPattern, pollOnce } = require('./poller');
const { createState } = require('./state');

test('determineStatus: not_running when session does not exist', () => {
  const status = determineStatus({ sessionExists: false, captureError: false, outputChanged: false, output: '', secondsSinceChange: 0, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'not_running');
});

test('determineStatus: unresponsive when capture errors', () => {
  const status = determineStatus({ sessionExists: true, captureError: true, outputChanged: false, output: '', secondsSinceChange: 0, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'unresponsive');
});

test('determineStatus: working when output changed', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: true, output: 'some output', secondsSinceChange: 0, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'working');
});

test('determineStatus: waiting_input when output ends with prompt pattern', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: false, output: 'Do you want to proceed? (y/n)', secondsSinceChange: 5, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'waiting_input');
});

test('determineStatus: idle when unchanged past idle threshold', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: false, output: 'nothing special', secondsSinceChange: 70, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'idle');
});

test('determineStatus: stale when unchanged past stale threshold', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: false, output: 'nothing special', secondsSinceChange: 400, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'stale');
});

test('determineStatus: idle (not working) when unchanged and below idle threshold', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: false, output: 'nothing special', secondsSinceChange: 5, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'idle');
});

test('matchesWaitingInputPattern detects common prompt strings', () => {
  assert.strictEqual(matchesWaitingInputPattern('foo\n> '), true);
  assert.strictEqual(matchesWaitingInputPattern('foo\n❯ '), true);
  assert.strictEqual(matchesWaitingInputPattern('Continue? (y/n)'), true);
  assert.strictEqual(matchesWaitingInputPattern('Do you want to proceed?'), true);
  assert.strictEqual(matchesWaitingInputPattern('normal output line'), false);
});
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd tmux-dashboard && node --test lib/poller.test.js`
Expected: FAIL（`./poller`モジュールが存在しない）

- [ ] **Step 3: determineStatus / matchesWaitingInputPattern を実装（pollOnce/startPollingは仮実装せず同一ファイルに実装する）**

```javascript
// tmux-dashboard/lib/poller.js
const WAITING_INPUT_PATTERNS = [
  /[❯>]\s*$/,
  /\(y\/n\)/i,
  /Do you want/i,
  /continue\?/i,
];

function matchesWaitingInputPattern(output) {
  const trimmed = (output || '').trimEnd();
  return WAITING_INPUT_PATTERNS.some((re) => re.test(trimmed));
}

function determineStatus({ sessionExists, captureError, outputChanged, output, secondsSinceChange, idleThresholdSec, staleThresholdSec }) {
  if (!sessionExists) return 'not_running';
  if (captureError) return 'unresponsive';
  if (outputChanged) return 'working';
  if (matchesWaitingInputPattern(output)) return 'waiting_input';
  if (secondsSinceChange >= staleThresholdSec) return 'stale';
  if (secondsSinceChange >= idleThresholdSec) return 'idle';
  return 'idle';
}

async function pollOnce({ agentsConfig, tmux, state, outputLines, idleThresholdSec, staleThresholdSec, now }) {
  const changed = [];
  const sessions = await tmux.listSessions();

  for (const agent of agentsConfig) {
    const prev = state.getAgent(agent.id);
    const sessionExists = sessions.includes(agent.session);
    let captureError = false;
    let output = prev ? prev.rawOutput : '';

    if (sessionExists) {
      try {
        output = await tmux.capturePane(agent.session, outputLines);
      } catch (err) {
        captureError = true;
      }
    }

    const outputChanged = sessionExists && !captureError && output !== (prev ? prev.rawOutput : undefined);
    const lastChangedAt = outputChanged || !prev ? now : prev.lastChangedAt;
    const secondsSinceChange = (now.getTime() - lastChangedAt.getTime()) / 1000;

    const status = determineStatus({
      sessionExists,
      captureError,
      outputChanged,
      output,
      secondsSinceChange,
      idleThresholdSec,
      staleThresholdSec,
    });

    state.setAgent(agent.id, {
      name: agent.name,
      session: agent.session,
      status,
      rawOutput: output,
      lastChangedAt,
    });

    if (!prev || prev.status !== status || outputChanged) {
      changed.push(agent.id);
    }
  }

  return changed;
}

function startPolling({ agentsConfig, tmux, state, config, onChange }) {
  async function runOnce() {
    const changed = await pollOnce({
      agentsConfig,
      tmux,
      state,
      outputLines: config.OUTPUT_LINES,
      idleThresholdSec: config.IDLE_THRESHOLD_SEC,
      staleThresholdSec: config.STALE_THRESHOLD_SEC,
      now: new Date(),
    });
    if (changed.length > 0) onChange(changed);
  }
  runOnce(); // 起動直後にstateを埋める（setIntervalの最初の発火を待たない）
  const timer = setInterval(runOnce, config.POLL_INTERVAL_MS);
  return () => clearInterval(timer);
}

module.exports = { matchesWaitingInputPattern, determineStatus, pollOnce, startPolling };
```

- [ ] **Step 4: determineStatus/matchesWaitingInputPatternのテストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test lib/poller.test.js`
Expected: PASS（8 tests のうち determineStatus/matchesWaitingInputPattern分。pollOnceのテストは次のステップで追加）

- [ ] **Step 5: pollOnceの失敗するテストを追加**

`tmux-dashboard/lib/poller.test.js`の末尾に追記:

```javascript
test('pollOnce marks not_running when session missing, and working on first-time output', async () => {
  const state = createState();
  const tmux = {
    listSessions: async () => ['cc-agent2'],
    capturePane: async (session) => `output for ${session}`,
  };
  const agentsConfig = [
    { id: 'agent1', name: 'A', session: 'cc-agent1' },
    { id: 'agent2', name: 'B', session: 'cc-agent2' },
  ];
  const now = new Date('2026-08-23T00:00:00.000Z');

  const changed = await pollOnce({ agentsConfig, tmux, state, outputLines: 200, idleThresholdSec: 60, staleThresholdSec: 300, now });

  assert.deepStrictEqual(changed.sort(), ['agent1', 'agent2']);
  assert.strictEqual(state.getAgent('agent1').status, 'not_running');
  assert.strictEqual(state.getAgent('agent2').status, 'working');
});

test('pollOnce keeps idle status and does not report change when output unchanged and no threshold crossed', async () => {
  const state = createState();
  state.setAgent('agent1', { name: 'A', session: 'cc-agent1', status: 'idle', rawOutput: 'same output', lastChangedAt: new Date('2026-08-23T00:00:00.000Z') });
  const tmux = {
    listSessions: async () => ['cc-agent1'],
    capturePane: async () => 'same output',
  };
  const agentsConfig = [{ id: 'agent1', name: 'A', session: 'cc-agent1' }];
  const now = new Date('2026-08-23T00:00:05.000Z');

  const changed = await pollOnce({ agentsConfig, tmux, state, outputLines: 200, idleThresholdSec: 60, staleThresholdSec: 300, now });

  assert.deepStrictEqual(changed, []);
  assert.strictEqual(state.getAgent('agent1').status, 'idle');
});
```

- [ ] **Step 6: テストを実行して失敗しないことを確認（実装は既にStep3で完了しているため成功するはず）**

Run: `cd tmux-dashboard && node --test lib/poller.test.js`
Expected: PASS（全10 tests）

- [ ] **Step 7: Commit**

```bash
git add tmux-dashboard/lib/poller.js tmux-dashboard/lib/poller.test.js
git commit -m "feat(tmux-dashboard): 状態判定ロジックとポーリングループを追加"
```

---

### Task 5: server.js — REST API

**Files:**
- Create: `tmux-dashboard/server.js`
- Test: `tmux-dashboard/server.test.js`

**Interfaces:**
- Consumes: `lib/tmux.js`（`listSessions/capturePane/sendKeys`）、`lib/state.js`（`createState/formatAgentSummary`）、`lib/poller.js`（`startPolling`）
- Produces:
  - `createApp({ state, tmux, agentsConfig })` → Express `app`インスタンス（テストで直接叩けるようexportする。実サーバー起動とWebSocketのアタッチはTask 6で行う`main()`側に持たせる）

- [ ] **Step 1: 失敗するテストを書く**

```javascript
// tmux-dashboard/server.test.js
const test = require('node:test');
const assert = require('node:assert');
const { createApp } = require('./server');
const { createState } = require('./lib/state');

function setupApp({ sessions = [], captureOutput = 'hello', sendKeysError = null } = {}) {
  const state = createState();
  state.setAgent('agent1', { name: 'A', session: 'cc-agent1', status: 'working', rawOutput: 'hello\nworld', lastChangedAt: new Date() });
  const tmux = {
    listSessions: async () => sessions,
    capturePane: async () => captureOutput,
    sendKeys: async () => {
      if (sendKeysError) throw new Error(sendKeysError);
    },
  };
  const agentsConfig = [
    { id: 'agent1', name: 'A', session: 'cc-agent1' },
    { id: 'agent2', name: 'B', session: 'cc-agent2' },
  ];
  const app = createApp({ state, tmux, agentsConfig });
  return { app, state };
}

test('GET /api/agents returns all agents with summary fields', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents`);
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.agents.length, 1); // agent2は未ポーリングなのでstateに無い→一覧には出さない
    assert.strictEqual(body.agents[0].id, 'agent1');
    assert.strictEqual(body.agents[0].status, 'working');
  } finally {
    server.close();
  }
});

test('GET /api/agents/:id/output returns full output for known id', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/agent1/output`);
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.output, 'hello\nworld');
  } finally {
    server.close();
  }
});

test('GET /api/agents/:id/output returns 404 for unknown id', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/unknown/output`);
    assert.strictEqual(res.status, 404);
  } finally {
    server.close();
  }
});

test('POST /api/agents/:id/send sends text and returns ok', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/agent1/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'hello agent' }),
    });
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.ok, true);
    assert.strictEqual(body.id, 'agent1');
  } finally {
    server.close();
  }
});

test('POST /api/agents/:id/send returns 400 when text missing', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/agent1/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    assert.strictEqual(res.status, 400);
  } finally {
    server.close();
  }
});

test('POST /api/agents/:id/send returns 404 for unknown id', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/unknown/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'hi' }),
    });
    assert.strictEqual(res.status, 404);
  } finally {
    server.close();
  }
});

test('POST /api/agents/broadcast sends to all configured agents and reports per-agent result', async () => {
  const { app } = setupApp({ sendKeysError: null });
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/broadcast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'hi all' }),
    });
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.ok, true);
    assert.strictEqual(body.results.length, 2);
  } finally {
    server.close();
  }
});
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd tmux-dashboard && node --test server.test.js`
Expected: FAIL（`./server`モジュールが存在しない）

- [ ] **Step 3: server.js を実装**

```javascript
// tmux-dashboard/server.js
const express = require('express');
const cors = require('cors');
const { formatAgentSummary } = require('./lib/state');

function findAgentConfig(agentsConfig, id) {
  return agentsConfig.find((a) => a.id === id);
}

function createApp({ state, tmux, agentsConfig }) {
  const app = express();
  app.use(cors());
  app.use(express.json());

  app.get('/api/agents', (req, res) => {
    const now = new Date();
    const agents = state
      .getAllIds()
      .map((id) => formatAgentSummary(id, state.getAgent(id), now));
    res.json({ agents });
  });

  app.get('/api/agents/:id/output', (req, res) => {
    const data = state.getAgent(req.params.id);
    if (!data) {
      res.status(404).json({ error: 'agent not found' });
      return;
    }
    res.json({ id: req.params.id, session: data.session, output: data.rawOutput });
  });

  app.post('/api/agents/:id/send', async (req, res) => {
    const { id } = req.params;
    const { text } = req.body || {};
    if (typeof text !== 'string' || text.length === 0) {
      res.status(400).json({ error: 'text is required' });
      return;
    }
    const agentConfig = findAgentConfig(agentsConfig, id);
    if (!agentConfig) {
      res.status(404).json({ error: 'agent not found' });
      return;
    }
    const data = state.getAgent(id);
    if (data && data.status === 'not_running') {
      res.status(409).json({ error: 'session not running' });
      return;
    }
    try {
      await tmux.sendKeys(agentConfig.session, text);
      res.json({ ok: true, id, sentAt: new Date().toISOString() });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/agents/broadcast', async (req, res) => {
    const { text } = req.body || {};
    if (typeof text !== 'string' || text.length === 0) {
      res.status(400).json({ error: 'text is required' });
      return;
    }
    const results = await Promise.all(
      agentsConfig.map(async (agentConfig) => {
        try {
          await tmux.sendKeys(agentConfig.session, text);
          return { id: agentConfig.id, ok: true };
        } catch (err) {
          return { id: agentConfig.id, ok: false, error: err.message };
        }
      }),
    );
    res.json({ ok: true, results });
  });

  return app;
}

module.exports = { createApp };
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test server.test.js`
Expected: PASS（7 tests）

- [ ] **Step 5: Commit**

```bash
git add tmux-dashboard/server.js tmux-dashboard/server.test.js
git commit -m "feat(tmux-dashboard): REST APIを実装"
```

---

### Task 6: WebSocket /ws とサーバー起動エントリポイント

**Files:**
- Modify: `tmux-dashboard/server.js`（`createApp`はそのまま、新たに`createWsServer`と`main`を追加）
- Test: `tmux-dashboard/server.test.js`（WebSocketのテストを追記）

**Interfaces:**
- Consumes: Task 5の`createApp`、Task 4の`startPolling`、Task 3の`formatAgentSummary`
- Produces:
  - `attachWebSocketServer({ httpServer, state, agentsConfig })` → `{ broadcastUpdate(changedIds: string[]): void, wss: WebSocketServer }`
  - `main()`（`config.json`と`agents.json`を読み込み、`createApp`でHTTPサーバーを起動し、`attachWebSocketServer`をアタッチし、`startPolling`の`onChange`で`broadcastUpdate`を呼ぶ。`require.main === module`のときのみ実行）

- [ ] **Step 1: 失敗するテストを書く（WebSocket接続時のスナップショット配信）**

`tmux-dashboard/server.test.js`に追記:

```javascript
const WebSocket = require('ws');
const { attachWebSocketServer } = require('./server');

test('WebSocket /ws sends a snapshot on connect', async () => {
  const { app, state } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  const agentsConfig = [
    { id: 'agent1', name: 'A', session: 'cc-agent1' },
    { id: 'agent2', name: 'B', session: 'cc-agent2' },
  ];
  attachWebSocketServer({ httpServer: server, state, agentsConfig });

  try {
    const ws = new WebSocket(`ws://localhost:${port}/ws`);
    const message = await new Promise((resolve, reject) => {
      ws.on('message', (data) => resolve(JSON.parse(data.toString())));
      ws.on('error', reject);
    });
    assert.strictEqual(message.type, 'snapshot');
    assert.strictEqual(message.agents.length, 1);
    ws.close();
  } finally {
    server.close();
  }
});

test('broadcastUpdate pushes an update message with only changed agents', async () => {
  const { app, state } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  const agentsConfig = [{ id: 'agent1', name: 'A', session: 'cc-agent1' }];
  const { broadcastUpdate } = attachWebSocketServer({ httpServer: server, state, agentsConfig });

  try {
    const ws = new WebSocket(`ws://localhost:${port}/ws`);
    await new Promise((resolve, reject) => {
      ws.on('message', () => resolve()); // snapshot受信を待つ
      ws.on('error', reject);
    });

    const updatePromise = new Promise((resolve, reject) => {
      ws.on('message', (data) => resolve(JSON.parse(data.toString())));
      ws.on('error', reject);
    });
    broadcastUpdate(['agent1']);
    const message = await updatePromise;
    assert.strictEqual(message.type, 'update');
    assert.strictEqual(message.agents.length, 1);
    assert.strictEqual(message.agents[0].id, 'agent1');
    ws.close();
  } finally {
    server.close();
  }
});
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd tmux-dashboard && node --test server.test.js`
Expected: FAIL（`attachWebSocketServer`が存在しない）

- [ ] **Step 3: server.js に WebSocket実装と main() を追加**

`tmux-dashboard/server.js`の`module.exports`より前に追記:

```javascript
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { WebSocketServer } = require('ws');
const { startPolling } = require('./lib/poller');
const tmuxLib = require('./lib/tmux');
const { createState } = require('./lib/state');

function attachWebSocketServer({ httpServer, state, agentsConfig }) {
  const wss = new WebSocketServer({ server: httpServer, path: '/ws' });

  wss.on('connection', (ws) => {
    const now = new Date();
    const agents = state
      .getAllIds()
      .map((id) => formatAgentSummary(id, state.getAgent(id), now));
    ws.send(JSON.stringify({ type: 'snapshot', agents }));
  });

  function broadcastUpdate(changedIds) {
    const now = new Date();
    const agents = changedIds
      .filter((id) => state.getAgent(id))
      .map((id) => formatAgentSummary(id, state.getAgent(id), now));
    if (agents.length === 0) return;
    const payload = JSON.stringify({ type: 'update', agents });
    wss.clients.forEach((client) => {
      if (client.readyState === client.OPEN) client.send(payload);
    });
  }

  return { wss, broadcastUpdate };
}

function main() {
  const configPath = path.join(__dirname, 'config.json');
  const agentsPath = path.join(__dirname, 'agents.json');
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  const agentsConfig = JSON.parse(fs.readFileSync(agentsPath, 'utf8'));

  const state = createState();
  const app = createApp({ state, tmux: tmuxLib, agentsConfig });
  const httpServer = http.createServer(app);
  const { broadcastUpdate } = attachWebSocketServer({ httpServer, state, agentsConfig });

  startPolling({
    agentsConfig,
    tmux: tmuxLib,
    state,
    config,
    onChange: broadcastUpdate,
  });

  httpServer.listen(config.PORT, () => {
    console.log(`tmux-dashboard server listening on port ${config.PORT}`);
  });
}

if (require.main === module) {
  main();
}
```

`module.exports`を以下に更新:

```javascript
module.exports = { createApp, attachWebSocketServer, main };
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test server.test.js`
Expected: PASS（全9 tests）

- [ ] **Step 5: Commit**

```bash
git add tmux-dashboard/server.js tmux-dashboard/server.test.js
git commit -m "feat(tmux-dashboard): WebSocket配信とサーバー起動エントリポイントを追加"
```

---

### Task 7: README.md（API仕様書）

**Files:**
- Create: `tmux-dashboard/README.md`

**Interfaces:**
- Consumes: Task 1〜6で確定した全API・設定ファイルの形式
- Produces: なし（ドキュメントのみ）

- [ ] **Step 1: README.md を作成**

```markdown
# tmux-dashboard

tmuxで並行実行している複数のClaude Codeセッションを監視・操作するAPI/WebSocketサーバー。

## セットアップ

\`\`\`bash
cd tmux-dashboard
npm install
cp agents.example.json agents.json
# agents.json を実際のtmuxセッションに合わせて編集
npm start
\`\`\`

デフォルトで `http://localhost:3000` で起動します。ポート等は `config.json` で変更できます。

tmuxコマンドはWSL経由（`wsl -e tmux ...`）で実行します。Windows上でこのサーバーを実行し、監視対象のtmuxセッションはWSL内で動作している前提です。

## agents.json

\`\`\`json
[
  { "id": "agent1", "name": "リサーチ担当", "session": "cc-agent1" }
]
\`\`\`

## config.json

| キー | 既定値 | 説明 |
|---|---|---|
| PORT | 3000 | HTTP/WebSocketのポート |
| POLL_INTERVAL_MS | 2500 | tmux poll間隔（ミリ秒） |
| IDLE_THRESHOLD_SEC | 60 | この秒数以上出力変化がなければ`idle` |
| STALE_THRESHOLD_SEC | 300 | この秒数以上出力変化がなければ`stale` |
| OUTPUT_LINES | 200 | capture-paneで取得する行数 |

## 状態(status)一覧

- `working`: 出力が変化中
- `waiting_input`: 出力末尾が確認プロンプトらしき文字列
- `idle`: 一定時間出力変化なし
- `stale`: 長時間出力変化なし（応答なし疑い）
- `not_running`: tmuxセッション未起動
- `unresponsive`: tmuxコマンド実行エラー

## API

### GET /api/agents

全エージェントの一覧・状態・直近出力・経過時間を返す。

\`\`\`json
{
  "agents": [
    {
      "id": "agent1",
      "name": "リサーチ担当",
      "session": "cc-agent1",
      "status": "working",
      "lastOutputPreview": "...(直近5行)...",
      "lastChangedAt": "2026-08-23T19:15:00.000Z",
      "elapsedSec": 12
    }
  ]
}
\`\`\`

### GET /api/agents/:id/output

指定エージェントの直近出力全文を返す。未登録idは404。

\`\`\`json
{ "id": "agent1", "session": "cc-agent1", "output": "...(capture-pane全文)..." }
\`\`\`

### POST /api/agents/:id/send

リクエストボディ: `{ "text": "指示文" }`

\`\`\`json
{ "ok": true, "id": "agent1", "sentAt": "2026-08-23T19:15:03.000Z" }
\`\`\`

エラー: text欠落→400、未登録id→404、`not_running`状態→409。

### POST /api/agents/broadcast

リクエストボディ: `{ "text": "指示文" }`

\`\`\`json
{
  "ok": true,
  "results": [
    { "id": "agent1", "ok": true },
    { "id": "agent2", "ok": false, "error": "session not found" }
  ]
}
\`\`\`

### WebSocket /ws

- 接続時: `{ "type": "snapshot", "agents": [...] }`（全件）
- 以降: `{ "type": "update", "agents": [...] }`（状態変化のあったエージェントのみ、`POLL_INTERVAL_MS`ごと）

## テスト

\`\`\`bash
npm test
\`\`\`
```

- [ ] **Step 2: Commit**

```bash
git add tmux-dashboard/README.md
git commit -m "docs(tmux-dashboard): READMEにAPI仕様を記載"
```

---

### Task 8: 疎通確認

**Files:**
- なし（動作確認のみ）

**Interfaces:**
- Consumes: Task 1〜7の全成果物

- [ ] **Step 1: 全テストを実行**

Run: `cd tmux-dashboard && npm test`
Expected: 全テストPASS（Task2〜6の合計約27 tests）

- [ ] **Step 2: agents.json を作成しサーバーを起動**

```bash
cd tmux-dashboard
cp agents.example.json agents.json
npm start
```
Expected: `tmux-dashboard server listening on port 3000` が出力される（Ctrl+Cで停止せず別ターミナルで次へ）。

- [ ] **Step 3: REST APIの疎通確認**

```bash
curl http://localhost:3000/api/agents
```
Expected: 200 OK、`{"agents":[...]}`（agents.example.jsonのセッションはWSL側に存在しない可能性が高いため、`status`は`not_running`になる想定。エラーにならず200が返ればOK）。

- [ ] **Step 4: サーバーを停止**

起動したターミナルで Ctrl+C。

- [ ] **Step 5: fresh context検証（別エージェントに要求充足を確認させる）**

CLAUDE.mdのDONE手順に従い、実装内容（このタスクで作成した全ファイル一覧）を会話の文脈を持たないエージェントに渡し、「この変更はユーザーの要求（tmux監視・4状態判定・4種のREST API・WebSocket差分配信・Node.js+Express+ws・単一コマンド起動・デフォルトポート3000・CORS有効・agents.json管理・認証なし）を満たすか」を検証させる。

- [ ] **Step 6: 最終bash判定**

```bash
#!/bin/bash
set -e
cd tmux-dashboard
git diff --stat --exit-code --quiet -- . && echo "NO CHANGES" && exit 1
npm test
echo "DONE"
```
