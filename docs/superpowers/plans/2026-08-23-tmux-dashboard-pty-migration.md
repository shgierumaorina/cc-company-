# tmux-dashboard node-pty移行 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tmux-dashboard`バックエンドのtmux/WSL依存を廃止し、node-ptyでバックエンドが`claude`プロセス自体を起動・保有・書き込みする方式に作り直す。

**Architecture:** `lib/tmux.js`を`lib/agentProcess.js`（node-pty薄いラッパー）に置き換え、`lib/poller.js`は状態判定の純粋関数（`determineStatus`/`matchesWaitingInputPattern`）のみ残す。新規`lib/manager.js`が起動時の全エージェントspawn・出力バッファのイベント駆動蓄積・定期的な状態再判定・書き込みを一手に担う。REST/WebSocket APIのエンドポイント形状は変更しないが、レスポンスの`session`フィールドは`cwd`にリネームする。

**Tech Stack:** 既存の`express`/`ws`/`cors`に加え、新規依存`node-pty`（ビルド不要・プリビルドバイナリで動作確認済み）。

**Spec:** [docs/superpowers/specs/2026-08-23-tmux-dashboard-pty-migration-design.md](../specs/2026-08-23-tmux-dashboard-pty-migration-design.md)

## Global Constraints

- 追加npm依存は`node-pty`のみ。
- `determineStatus`/`matchesWaitingInputPattern`のシグネチャ・挙動は変更しない（既存テストをそのまま流用するため）。
- 各タスク終了時点で`npm test`が全件パスする状態を維持する（トランジェントに壊れた状態のままタスクを終えない）。
- 実際の`claude`プロセスをnode-ptyで起動する統合確認（Task 7）は、実際に課金対象のClaude Codeセッションを起動する可能性があるため、**実行前に必ずユーザーに確認する**。
- 1コミットの変更は200行以内。超える場合はステップ単位で分割コミットする。
- フロントエンド（`public/index.html`）は`session`フィールドを参照していないため変更不要（Task 6でREADMEのみ更新）。

---

### Task 1: lib/agentProcess.js — node-ptyラッパー

**Files:**
- Modify: `tmux-dashboard/package.json`（`node-pty`を依存に追加）
- Create: `tmux-dashboard/lib/agentProcess.js`
- Test: `tmux-dashboard/lib/agentProcess.test.js`

**Interfaces:**
- Consumes: なし
- Produces:
  - `spawnAgentProcess({ command, args, cwd, cols, rows })` → node-ptyの`ptyProcess`インスタンス（`onData(cb)`, `onExit(cb)`, `write(text)`を持つ）
  - `writeToProcess(ptyProcess, text)` → `void`（`ptyProcess.write(text + '\r')`を呼ぶ）

- [ ] **Step 1: package.jsonにnode-ptyを追加してインストール**

`tmux-dashboard/package.json`の`"dependencies"`を以下に更新:

```json
  "dependencies": {
    "cors": "^2.8.5",
    "express": "^4.19.2",
    "node-pty": "^1.0.0",
    "ws": "^8.18.0"
  }
```

Run: `cd tmux-dashboard && npm install`
Expected: ビルドエラーなくインストール完了（プリビルドバイナリを使用）。

- [ ] **Step 2: 失敗するテストを書く**

```javascript
// tmux-dashboard/lib/agentProcess.test.js
const test = require('node:test');
const assert = require('node:assert');
const { spawnAgentProcess, writeToProcess } = require('./agentProcess');

test('spawnAgentProcess captures stdout from the spawned process', async () => {
  const proc = spawnAgentProcess({ command: 'cmd.exe', args: ['/c', 'echo HELLO_PTY_TEST'], cwd: process.cwd(), cols: 80, rows: 30 });
  const output = await new Promise((resolve) => {
    let buf = '';
    proc.onData((d) => { buf += d; });
    proc.onExit(() => resolve(buf));
  });
  assert.ok(output.includes('HELLO_PTY_TEST'));
});

test('writeToProcess sends text followed by a carriage return to a running shell', async () => {
  const proc = spawnAgentProcess({ command: 'cmd.exe', args: [], cwd: process.cwd(), cols: 80, rows: 30 });
  const output = await new Promise((resolve) => {
    let buf = '';
    let exitRequested = false;
    proc.onData((d) => {
      buf += d;
      if (!exitRequested && buf.includes('HELLO_FROM_WRITE')) {
        exitRequested = true;
        proc.write('exit\r');
      }
    });
    proc.onExit(() => resolve(buf));
    setTimeout(() => writeToProcess(proc, 'echo HELLO_FROM_WRITE'), 800);
  });
  assert.ok(output.includes('HELLO_FROM_WRITE'));
});
```

- [ ] **Step 3: テストを実行して失敗を確認**

Run: `cd tmux-dashboard && node --test lib/agentProcess.test.js`
Expected: FAIL（`./agentProcess`モジュールが存在しない）

- [ ] **Step 4: lib/agentProcess.js を実装**

```javascript
// tmux-dashboard/lib/agentProcess.js
const pty = require('node-pty');

function spawnAgentProcess({ command, args, cwd, cols, rows }) {
  return pty.spawn(command, args, {
    name: 'xterm-color',
    cols,
    rows,
    cwd,
    env: process.env,
  });
}

function writeToProcess(ptyProcess, text) {
  ptyProcess.write(text + '\r');
}

module.exports = { spawnAgentProcess, writeToProcess };
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test lib/agentProcess.test.js`
Expected: PASS（2 tests）

- [ ] **Step 6: Commit**

```bash
git add tmux-dashboard/package.json tmux-dashboard/package-lock.json tmux-dashboard/lib/agentProcess.js tmux-dashboard/lib/agentProcess.test.js
git commit -m "feat(tmux-dashboard): node-ptyラッパーを追加"
```

---

### Task 2: lib/poller.js — tmux依存部分を削除し状態判定ロジックのみ残す

**Files:**
- Modify: `tmux-dashboard/lib/poller.js`
- Modify: `tmux-dashboard/lib/poller.test.js`

**Interfaces:**
- Consumes: なし
- Produces: `matchesWaitingInputPattern`, `determineStatus`（シグネチャ・挙動は変更なし。以降`lib/manager.js`が利用する）

- [ ] **Step 1: poller.jsから`pollOnce`/`startPolling`を削除**

`tmux-dashboard/lib/poller.js`を以下の内容に置き換える:

```javascript
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

module.exports = { matchesWaitingInputPattern, determineStatus };
```

- [ ] **Step 2: poller.test.jsから`pollOnce`関連の2テストとその依存importを削除**

`tmux-dashboard/lib/poller.test.js`を以下の内容に置き換える（`determineStatus`/`matchesWaitingInputPattern`の8テストのみ残す）:

```javascript
const test = require('node:test');
const assert = require('node:assert');
const { determineStatus, matchesWaitingInputPattern } = require('./poller');

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

- [ ] **Step 3: テストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test lib/poller.test.js`
Expected: PASS（8 tests）

- [ ] **Step 4: 全体テストを実行し、他ファイルに影響がないことを確認**

Run: `cd tmux-dashboard && npm test`
Expected: 既存の他テスト（agentProcess, tmux, state, server）は引き続き全件PASS

- [ ] **Step 5: Commit**

```bash
git add tmux-dashboard/lib/poller.js tmux-dashboard/lib/poller.test.js
git commit -m "refactor(tmux-dashboard): poller.jsからtmux依存のポーリング処理を削除"
```

---

### Task 3: lib/state.js — `session`フィールドを`cwd`にリネーム

**Files:**
- Modify: `tmux-dashboard/lib/state.js`
- Modify: `tmux-dashboard/lib/state.test.js`

**Interfaces:**
- Consumes: なし
- Produces: `formatAgentSummary(id, data, now)`が返すオブジェクトの`session`フィールドが`cwd`に変わる（`data.cwd`を参照する）

- [ ] **Step 1: 失敗するテストを書く（既存テストを更新）**

`tmux-dashboard/lib/state.test.js`を以下の内容に置き換える:

```javascript
const test = require('node:test');
const assert = require('node:assert');
const { createState, formatAgentSummary } = require('./state');

test('setAgent then getAgent returns stored data', () => {
  const state = createState();
  state.setAgent('agent1', { name: 'A', cwd: 'C:\\proj1', status: 'working', rawOutput: 'line1\nline2', lastChangedAt: new Date('2026-08-23T00:00:00Z') });
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
  state.setAgent('a', { name: 'A', cwd: 'C:\\proj1', status: 'idle', rawOutput: '', lastChangedAt: new Date() });
  state.setAgent('b', { name: 'B', cwd: 'C:\\proj2', status: 'idle', rawOutput: '', lastChangedAt: new Date() });
  assert.deepStrictEqual(state.getAllIds().sort(), ['a', 'b']);
});

test('formatAgentSummary builds preview from last 5 lines, computes elapsedSec, and exposes cwd', () => {
  const lines = Array.from({ length: 10 }, (_, i) => `line${i}`);
  const lastChangedAt = new Date('2026-08-23T00:00:00.000Z');
  const now = new Date('2026-08-23T00:00:12.000Z');
  const summary = formatAgentSummary('agent1', {
    name: 'A', cwd: 'C:\\proj1', status: 'idle', rawOutput: lines.join('\n'), lastChangedAt,
  }, now);
  assert.strictEqual(summary.id, 'agent1');
  assert.strictEqual(summary.cwd, 'C:\\proj1');
  assert.strictEqual(summary.lastOutputPreview, lines.slice(-5).join('\n'));
  assert.strictEqual(summary.elapsedSec, 12);
  assert.strictEqual(summary.lastChangedAt, lastChangedAt.toISOString());
});
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd tmux-dashboard && node --test lib/state.test.js`
Expected: FAIL（`formatAgentSummary`の`cwd`が`undefined`のため`summary.cwd`のアサーションが失敗）

- [ ] **Step 3: state.jsの`formatAgentSummary`を更新**

`tmux-dashboard/lib/state.js`の`formatAgentSummary`関数内、`session: data.session,`を`cwd: data.cwd,`に置き換える。

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test lib/state.test.js`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
git add tmux-dashboard/lib/state.js tmux-dashboard/lib/state.test.js
git commit -m "refactor(tmux-dashboard): state.jsのsessionフィールドをcwdにリネーム"
```

---

### Task 4: lib/manager.js — spawn・出力蓄積・状態再判定・書き込みの統合管理

**Files:**
- Create: `tmux-dashboard/lib/manager.js`
- Test: `tmux-dashboard/lib/manager.test.js`

**Interfaces:**
- Consumes: `lib/poller.js`の`determineStatus`、`lib/agentProcess.js`の`spawnAgentProcess`/`writeToProcess`（既定値として使用、テスト時は差し替え可能）、`lib/state.js`の`createState()`が返すインスタンスと同じインターフェース
- Produces:
  - `createManager({ agentsConfig, state, config, spawn = spawnAgentProcess, write = writeToProcess })` → `{ start(onChange): stop, sendToAgent(id, text): void, spawnAll(): void, tick(): string[] }`
  - `spawnAll()`: `agentsConfig`の各エージェントについて`spawn`を呼び、成功なら`state`に`{name, cwd, status:'idle', rawOutput:'', lastChangedAt, changedSinceTick:false}`を登録し、`onData`/`onExit`を配線する。`spawn`が例外を投げたら`status:'unresponsive'`で登録する。
  - `tick()`: 全エージェントについて`secondsSinceChange`を計算し`determineStatus`で状態を再判定、`changedSinceTick`をリセットする。状態が変わった（または`changedSinceTick`が立っていた）idの配列を返す。`not_running`/`unresponsive`のエージェントは再判定をスキップする。
  - `sendToAgent(id, text)`: 該当idのプロセスが見つからなければ`Error('agent process not found')`をthrowする。見つかれば`write(proc, text)`を呼ぶ。
  - `start(onChange)`: `spawnAll()`を呼んだ後、`config.POLL_INTERVAL_MS`ごとに`tick()`を実行し、変化があれば`onChange(changedIds)`を呼ぶ`setInterval`を開始する。停止関数を返す。

- [ ] **Step 1: 失敗するテストを書く**

```javascript
// tmux-dashboard/lib/manager.test.js
const test = require('node:test');
const assert = require('node:assert');
const { createManager } = require('./manager');
const { createState } = require('./state');

function createFakeProc() {
  const dataListeners = [];
  const exitListeners = [];
  return {
    onData(cb) { dataListeners.push(cb); },
    onExit(cb) { exitListeners.push(cb); },
    emitData(d) { dataListeners.forEach((cb) => cb(d)); },
    emitExit() { exitListeners.forEach((cb) => cb()); },
  };
}

const BASE_CONFIG = { OUTPUT_LINES: 200, IDLE_THRESHOLD_SEC: 60, STALE_THRESHOLD_SEC: 300, POLL_INTERVAL_MS: 2500 };

test('spawnAll registers agents as idle and stores cwd', () => {
  const state = createState();
  const fakeProc = createFakeProc();
  const agentsConfig = [{ id: 'agent1', name: 'A', cwd: 'C:\\proj1' }];
  const manager = createManager({ agentsConfig, state, config: BASE_CONFIG, spawn: () => fakeProc });

  manager.spawnAll();

  const data = state.getAgent('agent1');
  assert.strictEqual(data.status, 'idle');
  assert.strictEqual(data.cwd, 'C:\\proj1');
});

test('spawnAll marks agent unresponsive when spawn throws', () => {
  const state = createState();
  const agentsConfig = [{ id: 'agent1', name: 'A', cwd: 'C:\\missing' }];
  const manager = createManager({
    agentsConfig, state, config: BASE_CONFIG,
    spawn: () => { throw new Error('ENOENT'); },
  });

  manager.spawnAll();

  assert.strictEqual(state.getAgent('agent1').status, 'unresponsive');
});

test('onData appends output, updates lastChangedAt, and marks changedSinceTick', () => {
  const state = createState();
  const fakeProc = createFakeProc();
  const agentsConfig = [{ id: 'agent1', name: 'A', cwd: 'C:\\proj1' }];
  const manager = createManager({ agentsConfig, state, config: BASE_CONFIG, spawn: () => fakeProc });

  manager.spawnAll();
  fakeProc.emitData('hello\n');

  const data = state.getAgent('agent1');
  assert.strictEqual(data.rawOutput, 'hello\n');
  assert.strictEqual(data.changedSinceTick, true);
});

test('onExit marks agent not_running', () => {
  const state = createState();
  const fakeProc = createFakeProc();
  const agentsConfig = [{ id: 'agent1', name: 'A', cwd: 'C:\\proj1' }];
  const manager = createManager({ agentsConfig, state, config: BASE_CONFIG, spawn: () => fakeProc });

  manager.spawnAll();
  fakeProc.emitExit();

  assert.strictEqual(state.getAgent('agent1').status, 'not_running');
});

test('tick promotes changedSinceTick to working and resets the flag', () => {
  const state = createState();
  const fakeProc = createFakeProc();
  const agentsConfig = [{ id: 'agent1', name: 'A', cwd: 'C:\\proj1' }];
  const manager = createManager({ agentsConfig, state, config: BASE_CONFIG, spawn: () => fakeProc });

  manager.spawnAll();
  fakeProc.emitData('hello\n');
  const changed = manager.tick();

  assert.deepStrictEqual(changed, ['agent1']);
  assert.strictEqual(state.getAgent('agent1').status, 'working');
  assert.strictEqual(state.getAgent('agent1').changedSinceTick, false);
});

test('tick skips not_running agents', () => {
  const state = createState();
  const fakeProc = createFakeProc();
  const agentsConfig = [{ id: 'agent1', name: 'A', cwd: 'C:\\proj1' }];
  const manager = createManager({ agentsConfig, state, config: BASE_CONFIG, spawn: () => fakeProc });

  manager.spawnAll();
  fakeProc.emitExit();
  const changed = manager.tick();

  assert.deepStrictEqual(changed, []);
  assert.strictEqual(state.getAgent('agent1').status, 'not_running');
});

test('sendToAgent writes text to the process for a running agent', () => {
  const state = createState();
  const fakeProc = createFakeProc();
  const agentsConfig = [{ id: 'agent1', name: 'A', cwd: 'C:\\proj1' }];
  const writeCalls = [];
  const manager = createManager({
    agentsConfig, state, config: BASE_CONFIG,
    spawn: () => fakeProc,
    write: (proc, text) => writeCalls.push({ proc, text }),
  });

  manager.spawnAll();
  manager.sendToAgent('agent1', 'hello');

  assert.strictEqual(writeCalls.length, 1);
  assert.strictEqual(writeCalls[0].text, 'hello');
});

test('sendToAgent throws for unknown agent id', () => {
  const state = createState();
  const manager = createManager({ agentsConfig: [], state, config: BASE_CONFIG, spawn: () => createFakeProc() });

  assert.throws(() => manager.sendToAgent('unknown', 'hi'), /agent process not found/);
});
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `cd tmux-dashboard && node --test lib/manager.test.js`
Expected: FAIL（`./manager`モジュールが存在しない）

- [ ] **Step 3: lib/manager.js を実装**

```javascript
// tmux-dashboard/lib/manager.js
const { determineStatus } = require('./poller');
const { spawnAgentProcess, writeToProcess } = require('./agentProcess');

const PTY_COLS = 120;
const PTY_ROWS = 30;

function createManager({ agentsConfig, state, config, spawn = spawnAgentProcess, write = writeToProcess }) {
  const processes = new Map();

  function spawnAll() {
    const now = new Date();
    for (const agent of agentsConfig) {
      try {
        const proc = spawn({ command: 'claude', args: [], cwd: agent.cwd, cols: PTY_COLS, rows: PTY_ROWS });
        processes.set(agent.id, proc);
        state.setAgent(agent.id, {
          name: agent.name,
          cwd: agent.cwd,
          status: 'idle',
          rawOutput: '',
          lastChangedAt: now,
          changedSinceTick: false,
        });

        proc.onData((data) => {
          const prev = state.getAgent(agent.id);
          if (!prev) return;
          const lines = (prev.rawOutput + data).split('\n');
          const trimmed = lines.slice(-config.OUTPUT_LINES).join('\n');
          state.setAgent(agent.id, {
            ...prev,
            rawOutput: trimmed,
            lastChangedAt: new Date(),
            changedSinceTick: true,
          });
        });

        proc.onExit(() => {
          const prev = state.getAgent(agent.id);
          if (!prev) return;
          state.setAgent(agent.id, { ...prev, status: 'not_running' });
        });
      } catch (err) {
        state.setAgent(agent.id, {
          name: agent.name,
          cwd: agent.cwd,
          status: 'unresponsive',
          rawOutput: '',
          lastChangedAt: now,
          changedSinceTick: false,
        });
      }
    }
  }

  function tick() {
    const now = new Date();
    const changed = [];
    for (const agent of agentsConfig) {
      const prev = state.getAgent(agent.id);
      if (!prev || prev.status === 'not_running' || prev.status === 'unresponsive') continue;
      const secondsSinceChange = (now.getTime() - prev.lastChangedAt.getTime()) / 1000;
      const status = determineStatus({
        sessionExists: true,
        captureError: false,
        outputChanged: prev.changedSinceTick,
        output: prev.rawOutput,
        secondsSinceChange,
        idleThresholdSec: config.IDLE_THRESHOLD_SEC,
        staleThresholdSec: config.STALE_THRESHOLD_SEC,
      });
      if (status !== prev.status || prev.changedSinceTick) changed.push(agent.id);
      state.setAgent(agent.id, { ...prev, status, changedSinceTick: false });
    }
    return changed;
  }

  function sendToAgent(id, text) {
    const proc = processes.get(id);
    if (!proc) {
      throw new Error('agent process not found');
    }
    write(proc, text);
  }

  function start(onChange) {
    spawnAll();
    const timer = setInterval(() => {
      const changed = tick();
      if (changed.length > 0) onChange(changed);
    }, config.POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }

  return { start, sendToAgent, spawnAll, tick };
}

module.exports = { createManager };
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test lib/manager.test.js`
Expected: PASS（8 tests）

- [ ] **Step 5: Commit**

```bash
git add tmux-dashboard/lib/manager.js tmux-dashboard/lib/manager.test.js
git commit -m "feat(tmux-dashboard): spawn・出力蓄積・状態再判定を統合するmanagerを追加"
```

---

### Task 5: server.js — tmux/pollerからmanagerへの配線切り替え、旧ファイルの削除

**Files:**
- Modify: `tmux-dashboard/server.js`
- Modify: `tmux-dashboard/server.test.js`
- Delete: `tmux-dashboard/lib/tmux.js`
- Delete: `tmux-dashboard/lib/tmux.test.js`

**Interfaces:**
- Consumes: `lib/manager.js`の`createManager`、`lib/state.js`の`formatAgentSummary`/`createState`
- Produces: `createApp({ state, manager, agentsConfig })`（旧`{state, tmux, agentsConfig}`から変更）

- [ ] **Step 1: server.test.jsを新インターフェース向けに書き換える（失敗させる）**

`tmux-dashboard/server.test.js`の内容全体を以下に置き換える:

```javascript
const test = require('node:test');
const assert = require('node:assert');
const WebSocket = require('ws');
const { createApp, attachWebSocketServer } = require('./server');
const { createState } = require('./lib/state');

function setupApp({ writeError = null } = {}) {
  const state = createState();
  state.setAgent('agent1', { name: 'A', cwd: 'C:\\proj1', status: 'working', rawOutput: 'hello\nworld', lastChangedAt: new Date() });
  const writeCalls = [];
  const manager = {
    sendToAgent: (id, text) => {
      if (writeError) throw new Error(writeError);
      writeCalls.push({ id, text });
    },
  };
  const agentsConfig = [
    { id: 'agent1', name: 'A', cwd: 'C:\\proj1' },
    { id: 'agent2', name: 'B', cwd: 'C:\\proj2' },
  ];
  const app = createApp({ state, manager, agentsConfig });
  return { app, state, writeCalls };
}

test('GET /api/agents returns all agents with summary fields', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents`);
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.agents.length, 1); // agent2は未spawn扱いなのでstateに無い→一覧には出さない
    assert.strictEqual(body.agents[0].id, 'agent1');
    assert.strictEqual(body.agents[0].status, 'working');
  } finally {
    server.close();
  }
});

test('GET /api/agents/:id/output returns full output and cwd for known id', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/agent1/output`);
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.output, 'hello\nworld');
    assert.strictEqual(body.cwd, 'C:\\proj1');
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

test('POST /api/agents/:id/send writes text via manager and returns ok', async () => {
  const { app, writeCalls } = setupApp();
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
    assert.strictEqual(writeCalls.length, 1);
    assert.strictEqual(writeCalls[0].text, 'hello agent');
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
  const { app } = setupApp();
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

test('WebSocket /ws sends a snapshot on connect', async () => {
  const { app, state } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  const agentsConfig = [
    { id: 'agent1', name: 'A', cwd: 'C:\\proj1' },
    { id: 'agent2', name: 'B', cwd: 'C:\\proj2' },
  ];
  try {
    attachWebSocketServer({ httpServer: server, state, agentsConfig });
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
  const agentsConfig = [{ id: 'agent1', name: 'A', cwd: 'C:\\proj1' }];

  try {
    const { broadcastUpdate } = attachWebSocketServer({ httpServer: server, state, agentsConfig });
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
Expected: FAIL（`createApp`が`manager`ではなく`tmux`を期待しているため、送信系テストが失敗する）

- [ ] **Step 3: server.js を新インターフェース向けに書き換える**

`tmux-dashboard/server.js`の内容全体を以下に置き換える:

```javascript
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const express = require('express');
const cors = require('cors');
const { WebSocketServer } = require('ws');
const { formatAgentSummary, createState } = require('./lib/state');
const { createManager } = require('./lib/manager');

function findAgentConfig(agentsConfig, id) {
  return agentsConfig.find((a) => a.id === id);
}

function createApp({ state, manager, agentsConfig }) {
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
    res.json({ id: req.params.id, cwd: data.cwd, output: data.rawOutput });
  });

  app.post('/api/agents/:id/send', (req, res) => {
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
      res.status(409).json({ error: 'process not running' });
      return;
    }
    try {
      manager.sendToAgent(id, text);
      res.json({ ok: true, id, sentAt: new Date().toISOString() });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/agents/broadcast', (req, res) => {
    const { text } = req.body || {};
    if (typeof text !== 'string' || text.length === 0) {
      res.status(400).json({ error: 'text is required' });
      return;
    }
    const results = agentsConfig.map((agentConfig) => {
      try {
        manager.sendToAgent(agentConfig.id, text);
        return { id: agentConfig.id, ok: true };
      } catch (err) {
        return { id: agentConfig.id, ok: false, error: err.message };
      }
    });
    res.json({ ok: true, results });
  });

  return app;
}

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
  const manager = createManager({ agentsConfig, state, config });
  const app = createApp({ state, manager, agentsConfig });
  const httpServer = http.createServer(app);
  const { broadcastUpdate } = attachWebSocketServer({ httpServer, state, agentsConfig });

  manager.start(broadcastUpdate);

  httpServer.listen(config.PORT, () => {
    console.log(`tmux-dashboard server listening on port ${config.PORT}`);
  });
}

if (require.main === module) {
  main();
}

module.exports = { createApp, attachWebSocketServer, main };
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `cd tmux-dashboard && node --test server.test.js`
Expected: PASS（9 tests）

- [ ] **Step 5: lib/tmux.jsとlib/tmux.test.jsを削除**

```bash
cd tmux-dashboard
rm lib/tmux.js lib/tmux.test.js
```

- [ ] **Step 6: 全体テストを実行し、削除後も全件パスすることを確認**

Run: `cd tmux-dashboard && npm test`
Expected: 全件PASS（agentProcess:2, poller:8, state:4, manager:8, server:9 = 31 tests）

- [ ] **Step 7: Commit**

```bash
git add tmux-dashboard/server.js tmux-dashboard/server.test.js
git rm tmux-dashboard/lib/tmux.js tmux-dashboard/lib/tmux.test.js
git commit -m "refactor(tmux-dashboard): server.jsをmanager経由の配線に切り替え、tmux.jsを削除"
```

---

### Task 6: agents.json新フォーマットとREADME更新

**Files:**
- Modify: `tmux-dashboard/agents.example.json`
- Modify: `tmux-dashboard/README.md`

**Interfaces:**
- Consumes: Task 1〜5で確定した新API仕様・新agents.jsonフォーマット
- Produces: なし（設定サンプル・ドキュメントのみ）

- [ ] **Step 1: agents.example.jsonを新フォーマットに更新**

```json
[
  { "id": "agent1", "name": "リサーチ担当", "cwd": "C:\\path\\to\\project1" },
  { "id": "agent2", "name": "コンテンツ担当", "cwd": "C:\\path\\to\\project2" }
]
```

- [ ] **Step 2: README.mdを更新**

`tmux-dashboard/README.md`の該当箇所を以下のように書き換える。

「## セットアップ」節のtmux/WSLに関する説明を置き換え:

```markdown
## セットアップ

\`\`\`bash
cd tmux-dashboard
npm install
cp agents.example.json agents.json
# agents.json を実際に監視したいディレクトリに合わせて編集
npm start
\`\`\`

デフォルトで \`http://localhost:3000\` で起動します。ポート等は \`config.json\` で変更できます。

サーバー起動時に、\`agents.json\` に登録した各エージェントについて \`claude\` プロセスを対応する \`cwd\`（作業ディレクトリ）で自動的に起動します（node-pty使用）。あらかじめターミナルを手動で開いておく必要はありません。
```

「## agents.json」節を置き換え:

```markdown
## agents.json

\`\`\`json
[
  { "id": "agent1", "name": "リサーチ担当", "cwd": "C:\\\\path\\\\to\\\\project1" }
]
\`\`\`

各エージェントは \`claude\` を \`cwd\` で起動する。コマンド自体（\`claude\`固定）は変更できない。
```

「## 状態(status)一覧」節を置き換え:

```markdown
## 状態(status)一覧

- \`working\`: 出力が変化中
- \`waiting_input\`: 出力末尾が確認プロンプトらしき文字列
- \`idle\`: 一定時間出力変化なし
- \`stale\`: 長時間出力変化なし（応答なし疑い）
- \`not_running\`: プロセス未起動、またはクラッシュ・終了済み（自動再起動はしない）
- \`unresponsive\`: プロセスのspawn自体に失敗（\`cwd\`が存在しない、\`claude\`コマンドが見つからない等）
```

`GET /api/agents`のレスポンス例の`"session": "cc-agent1"`を`"cwd": "C:\\\\path\\\\to\\\\project1"`に置き換える。

`GET /api/agents/:id/output`のレスポンス例の`"session": "cc-agent1"`を`"cwd": "C:\\\\path\\\\to\\\\project1"`に置き換える。

- [ ] **Step 3: Commit**

```bash
git add tmux-dashboard/agents.example.json tmux-dashboard/README.md
git commit -m "docs(tmux-dashboard): node-pty移行に合わせてagents.json例とREADMEを更新"
```

---

### Task 7: 統合確認

**Files:**
- なし（動作確認のみ）

**Interfaces:**
- Consumes: Task 1〜6の全成果物

- [ ] **Step 1: 全ユニットテストを実行**

Run: `cd tmux-dashboard && npm test`
Expected: 全件PASS（31 tests）

- [ ] **Step 2: ユーザーに実クロード起動の確認を取る**

**この統合確認は実際に`claude`プロセス（課金対象のClaude Codeセッション）を起動する。実行前に必ずユーザーに「実際にclaudeプロセスを起動して確認してよいか」を確認する。** 承認が得られない場合はStep 3〜5をスキップし、Step 1（ユニットテスト）の結果のみで報告する。

- [ ] **Step 3: agents.jsonを実在するディレクトリで用意し、サーバーを起動**

承認が得られた場合のみ実施。`agents.json`の`cwd`を実在する軽量なテスト用ディレクトリ（例: `tmux-dashboard`自身）に設定し、`node server.js`を起動する。

- [ ] **Step 4: Browser toolでダッシュボードを開き、実プロセスの状態遷移を確認**

`npm run serve`でフロントエンドも起動し、`http://localhost:8080`をBrowser toolで開く。エージェントカードの状態が`idle`または`working`（tmuxではなく実プロセスの出力を反映していること）になることを確認する。可能であれば個別送信で簡単なテキストを送り、`claude`側に反映されることを確認する。

- [ ] **Step 5: 確認後、起動したclaudeプロセス・サーバーを終了する**

- [ ] **Step 6: fresh context検証**

会話の文脈を持たないエージェントに、`tmux-dashboard/lib/agentProcess.js`, `lib/manager.js`, `lib/poller.js`, `lib/state.js`, `server.js`, `agents.example.json`, `README.md`を読ませ、元の要求（tmux/WSL依存を廃止しnode-ptyでバックエンドがclaudeプロセスを自前起動・管理する、既存のAPI/WebSocket形状は維持、`session`→`cwd`リネーム、プロセス終了時は`not_running`表示のみ）を満たしているか検証させる。

- [ ] **Step 7: 最終bash判定**

```bash
#!/bin/bash
set -e
cd tmux-dashboard
git diff <base-branch> --stat --exit-code --quiet -- . && echo "NO CHANGES" && exit 1
npm test
echo "DONE"
```
