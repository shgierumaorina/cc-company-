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
