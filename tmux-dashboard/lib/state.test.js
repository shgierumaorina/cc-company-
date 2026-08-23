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
